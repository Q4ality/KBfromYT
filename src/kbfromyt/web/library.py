from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import time
from contextlib import nullcontext
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

from pydantic import Field, field_validator

from kbfromyt.chat.history import History
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.ingest import enumerate_videos, fetch_video
from kbfromyt.ingest_errors import IngestError, classify_ingest_error
from kbfromyt.models import Contract, VideoInput
from kbfromyt.processing import process
from kbfromyt.semantic import FastEmbedder, SemanticIndex
from kbfromyt.store import Store

ACTIVE = {"queued", "listing", "downloading", "processing", "indexing"}


class PlaylistRequest(Contract):
    url: str = Field(max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    languages: list[str] = Field(default_factory=lambda: ["ru", "en"], min_length=1, max_length=5)

    @field_validator("url")
    @classmethod
    def playlist_url(cls, value: str) -> str:
        import re

        url = urlparse(value.strip())
        playlist = parse_qs(url.query).get("list", [""])[0]
        if (
            url.scheme != "https"
            or url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}
            or url.path not in {"/playlist", "/watch"}
            or url.username
            or url.password
            or url.port not in {None, 443}
            or not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", playlist)
        ):
            raise ValueError("Use an HTTPS YouTube playlist URL containing list=...")
        return "https://www.youtube.com/playlist?" + urlencode({"list": playlist})

    @field_validator("languages")
    @classmethod
    def language_codes(cls, values: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", v) for v in values):
            raise ValueError("Use caption language codes such as ru, en or zh-Hans")
        return list(dict.fromkeys(values))


class Library:
    def __init__(self, service: ChatService, history: History):
        self.service, self.history = service, history
        self.task: asyncio.Task | None = None
        self.job: dict | None = None
        self.stopping = False
        self.cooldown_until = history.import_cooldown()
        for job in history.jobs():
            if job["status"] in ACTIVE:
                job.update(status="failed", message="Interrupted by server restart. Retry the job.")
                history.save_job(job)

    def status(self) -> dict:
        if self.service.corpus:
            sources = list(self.service.corpus.videos.values())
        else:
            with Store(self.service.config.db) as store:
                sources = store.videos()
        videos = [
            {
                "id": p.video.video_id,
                "title": p.video.title,
                "channel": p.video.channel,
                "language": p.video.language,
                "chunks": len(p.chunks),
            }
            for p in sources
        ]
        marker = self.service.config.index_dir / "complete.json"
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}
        return {
            "index": {
                key: metadata.get(key)
                for key in (
                    "index_version",
                    "count",
                    "documents",
                    "token_limit",
                    "max_window_tokens",
                )
            },
            "videos": videos,
            "playlists": self.history.playlists(),
            "jobs": self.history.jobs(),
            "active_job": self.job if self.active else None,
            "import_retry_not_before": self.cooldown_until,
        }

    def overview(self, playlist: str | None = None, offset: int = 0, limit: int = 10) -> dict:
        with Store(self.service.config.db) as store:
            summaries = store.overviews()
        if playlist:
            selected = next((p for p in self.history.playlists() if p["id"] == playlist), None)
            if selected is None:
                raise KeyError("Playlist not found")
            summaries = [s for s in summaries if s.video_id in selected["video_ids"]]
        page = summaries[offset : offset + limit]
        return {
            "method": "extractive",
            "total_videos": len(summaries),
            "videos": [s.model_dump() for s in page],
            "offset": offset,
            "has_more": offset + len(page) < len(summaries),
            "updating": self.active,
            "playlist": playlist,
        }

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()

    def update(self, **values) -> None:
        self.job.update(values, updated=time.time())
        self.history.save_job(self.job)

    def start(self, request: PlaylistRequest | None = None) -> dict:
        if self.active:
            raise ValueError("A library job is already running.")
        if request and time.time() < self.cooldown_until:
            remaining = math.ceil(self.cooldown_until - time.time())
            raise ValueError(
                f"YouTube downloads are paused. Wait {remaining} seconds before retrying. "
                "YouTube may require a longer wait; existing library chat still works."
            )
        self.job = {
            "id": uuid4().hex,
            "kind": "import" if request else "rebuild",
            "status": "queued",
            "message": "Waiting for active questions to finish.",
            "created": time.time(),
            "updated": time.time(),
            "completed": 0,
            "total": 0,
            "failed": 0,
            "skipped": 0,
            "indexed": 0,
            "results": [],
            "url": request.url if request else None,
            "request": request.model_dump(mode="json") if request else None,
        }
        self.history.save_job(self.job)
        self.service.maintenance = True
        self.task = asyncio.create_task(self.run(request))
        return dict(self.job)

    async def run(self, request: PlaylistRequest | None) -> None:
        try:
            async with self.service.operation_lock:
                inputs: list[VideoInput] = []
                blocked: IngestError | None = None
                if request:
                    self.update(status="listing", message="Listing playlist videos…")
                    ids = await asyncio.to_thread(enumerate_videos, request.url, request.limit)
                    if not ids:
                        raise IngestError(
                            "playlist_empty", "The playlist returned no videos.", stage="listing"
                        )
                    self.update(status="downloading", total=len(ids))
                    for number, vid in enumerate(ids, 1):
                        if self.stopping:
                            raise RuntimeError("Server is shutting down. Retry the job.")
                        self.update(message=f"Fetching captions {number}/{len(ids)}: {vid}")
                        stage = "captions"
                        try:
                            video = await asyncio.to_thread(fetch_video, vid, request.languages)
                            stage = "processing"
                            await asyncio.to_thread(process, video)
                            inputs.append(video)
                            result = {"video_id": vid, "title": video.title, "status": "downloaded"}
                        except Exception as exc:
                            failure = classify_ingest_error(exc, stage)
                            result = {
                                "video_id": vid,
                                "status": "failed",
                                **failure.details(),
                                "error_type": type(exc.__cause__ or exc).__name__,
                            }
                            self.job["failed"] += 1
                            if failure.stop_collection:
                                blocked = failure
                                self.cooldown_until = time.time() + failure.retry_after_seconds
                                self.update(
                                    retry_not_before=self.cooldown_until, error_code=failure.code
                                )
                        self.job["results"].append(result)
                        self.update(completed=number)
                        if blocked:
                            for skipped in ids[number:]:
                                self.job["results"].append(
                                    {
                                        "video_id": skipped,
                                        "status": "not_attempted",
                                        "message": (
                                            "Not requested after the connection-wide "
                                            "YouTube failure. Retry later."
                                        ),
                                    }
                                )
                            self.update(skipped=len(ids) - number)
                            break
                    if not inputs:
                        if blocked:
                            raise blocked
                        raise IngestError(
                            "no_usable_captions",
                            "No usable captions were downloaded. Check the per-video reasons "
                            "and requested languages before retrying.",
                        )
                self.update(
                    status="processing", message="Backing up and cleaning transcript chunks…"
                )
                changed = await asyncio.to_thread(self.process, inputs)
                self.update(
                    status="indexing", message="Building the local search index…", changed=changed
                )
                await asyncio.to_thread(self.rebuild)
                if request:
                    playlist_id = parse_qs(urlparse(request.url).query)["list"][0]
                    previous = next(
                        (p for p in self.history.playlists() if p["id"] == playlist_id), {}
                    )
                    selected = [v.video_id for v in inputs]
                    if self.job["failed"] or self.job["skipped"]:
                        selected = list(dict.fromkeys([*previous.get("video_ids", []), *selected]))
                    self.history.save_playlist(
                        {
                            **previous,
                            "id": playlist_id,
                            "url": request.url,
                            "video_ids": selected,
                            "updated": time.time(),
                        }
                    )
                for result in self.job["results"]:
                    if result["status"] == "downloaded":
                        result["status"] = "indexed"
                self.update(
                    indexed=len(inputs),
                    status="partial" if self.job["failed"] else "completed",
                    message=f"Indexed {len(inputs)} videos before downloads were paused. {blocked}"
                    if blocked
                    else "Library ready. Some videos failed; see details."
                    if self.job["failed"]
                    else "Library ready. Verified the existing index; no embeddings recomputed."
                    if self.job.get("index_reused")
                    else "Library ready for questions.",
                    finished=time.time(),
                )
        except Exception as exc:
            # A failed write/index never leaves a stale corpus ready for questions.
            with Store(self.service.config.db) as store:
                stale = bool(
                    self.service.corpus
                    and (
                        self.service.corpus.snapshot != store.snapshot_hash()
                        or self.service.corpus.semantic
                        and not self.service.corpus.semantic.manifest.exists()
                    )
                )
            if stale or self.job["status"] == "indexing":
                self.service.readiness_error = (
                    "Index update failed. Use Clean and rebuild to repair the library."
                )
            failure = classify_ingest_error(exc, self.job["status"])
            if failure.stop_collection:
                self.cooldown_until = max(
                    self.cooldown_until, time.time() + failure.retry_after_seconds
                )
            self.update(
                status="blocked" if failure.stop_collection else "failed",
                retry_not_before=self.cooldown_until,
                finished=time.time(),
                **failure.details(),
            )
        finally:
            self.service.maintenance = False

    def process(self, inputs: list[VideoInput]) -> int:
        config = self.service.config
        lock = self.service.corpus.lock if self.service.corpus else nullcontext()
        with lock, Store(config.db) as store:
            backups = config.db.parent / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backups / f"before-{self.job['id']}.sqlite3") as target:
                store.db.backup(target)
            changed = store.reprocess()
            changed += sum(store.import_video(video) for video in inputs)
        return changed

    def index_progress(self, stage: str, completed: int, total: int) -> None:
        messages = {
            "preparing": "Preparing source documents",
            "checking": "Checking saved embedding windows",
            "pruning": "Removing obsolete embedding windows",
            "embedding": "Embedding and saving source windows",
            "current": "Saved index verified; reusing existing embeddings",
        }
        self.update(
            index_stage=stage,
            index_completed=completed,
            index_total=total,
            index_reused=stage == "current",
            message=f"{messages[stage]}: {completed:,}/{total:,}.",
        )

    def rebuild(self) -> None:
        service = self.service
        if service.corpus:
            service.corpus.rebuild(progress=self.index_progress, skip_current=True)
        else:
            if service.config.semantic:
                index = SemanticIndex(
                    service.config.index_dir, FastEmbedder(service.config.embedding_model)
                )
                try:
                    with Store(service.config.db) as store:
                        index.rebuild(store, progress=self.index_progress, skip_current=True)
                finally:
                    index.close()
            service.corpus = Corpus(service.config)
        service.readiness_error = None

    async def close(self) -> None:
        self.stopping = True
        if self.task:
            await self.task
