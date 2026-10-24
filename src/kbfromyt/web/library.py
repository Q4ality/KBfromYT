from __future__ import annotations

import asyncio
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
        return {
            "videos": videos,
            "playlists": self.history.playlists(),
            "jobs": self.history.jobs(),
            "active_job": self.job if self.active else None,
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
            "results": [],
            "url": request.url if request else None,
        }
        self.history.save_job(self.job)
        self.service.maintenance = True
        self.task = asyncio.create_task(self.run(request))
        return dict(self.job)

    async def run(self, request: PlaylistRequest | None) -> None:
        try:
            async with self.service.operation_lock:
                inputs: list[VideoInput] = []
                if request:
                    self.update(status="listing", message="Listing playlist videos…")
                    ids = await asyncio.to_thread(enumerate_videos, request.url, request.limit)
                    if not ids:
                        raise ValueError("The playlist returned no videos.")
                    self.update(status="downloading", total=len(ids))
                    for number, vid in enumerate(ids, 1):
                        if self.stopping:
                            raise RuntimeError("Server is shutting down. Retry the job.")
                        self.update(message=f"Fetching captions {number}/{len(ids)}: {vid}")
                        try:
                            video = await asyncio.to_thread(fetch_video, vid, request.languages)
                            await asyncio.to_thread(process, video)
                            inputs.append(video)
                            result = {"video_id": vid, "title": video.title, "status": "downloaded"}
                        except Exception:
                            result = {
                                "video_id": vid,
                                "status": "failed",
                                "message": "Could not fetch metadata or requested captions.",
                            }
                            self.job["failed"] += 1
                        self.job["results"].append(result)
                        self.update(completed=number)
                    if not inputs:
                        raise ValueError(
                            "No usable captions were downloaded. Check per-video results."
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
                    self.history.save_playlist(
                        {
                            "id": parse_qs(urlparse(request.url).query)["list"][0],
                            "url": request.url,
                            "video_ids": [v.video_id for v in inputs],
                            "updated": time.time(),
                        }
                    )
                for result in self.job["results"]:
                    if result["status"] == "downloaded":
                        result["status"] = "indexed"
                self.update(
                    status="partial" if self.job["failed"] else "completed",
                    message="Library ready. Some videos failed; see details."
                    if self.job["failed"]
                    else "Library ready for questions.",
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
            message = (
                str(exc)
                if isinstance(exc, (ValueError, RuntimeError))
                else "Library update failed. Retry the job."
            )
            self.update(status="failed", message=message)
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

    def rebuild(self) -> None:
        service = self.service
        if service.corpus:
            service.corpus.rebuild()
        else:
            if service.config.semantic:
                index = SemanticIndex(
                    service.config.index_dir, FastEmbedder(service.config.embedding_model)
                )
                try:
                    with Store(service.config.db) as store:
                        index.rebuild(store)
                finally:
                    index.close()
            service.corpus = Corpus(service.config)
        service.readiness_error = None

    async def close(self) -> None:
        self.stopping = True
        if self.task:
            await self.task
