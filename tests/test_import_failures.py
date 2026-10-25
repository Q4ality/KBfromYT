import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from requests import ConnectionError, HTTPError, Timeout
from youtube_transcript_api import IpBlocked, NoTranscriptFound, TranscriptsDisabled
from yt_dlp.utils import DownloadError

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.history import History
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.ingest_errors import classify_ingest_error
from kbfromyt.web.library import Library, PlaylistRequest
from tests.test_chat import ScriptedProvider


@pytest.mark.parametrize(
    "exception,stage,code,stops",
    [
        (IpBlocked("abcdefghijk"), "captions", "youtube_blocked", True),
        (
            HTTPError("private URL", response=SimpleNamespace(status_code=429)),
            "metadata",
            "youtube_blocked",
            True,
        ),
        (
            NoTranscriptFound("abcdefghijk", ["en"], []),
            "captions",
            "caption_language_unavailable",
            False,
        ),
        (TranscriptsDisabled("abcdefghijk"), "captions", "captions_unavailable", False),
        (ConnectionError("private URL"), "captions", "network_error", True),
        (Timeout("private URL"), "captions", "network_timeout", False),
        (DownloadError("private URL"), "metadata", "metadata_unavailable", False),
        (DownloadError("private URL"), "listing", "playlist_unavailable", False),
        (ValueError("private URL"), "processing", "invalid_transcript", False),
        (RuntimeError("private URL"), "indexing", "index_update_failed", False),
        (RuntimeError("private URL"), "captions", "ingestion_failed", False),
    ],
)
def test_classification_separates_causes_without_leaking_upstream_text(
    exception, stage, code, stops
):
    error = classify_ingest_error(exception, stage)
    assert error.code == code and error.stage == stage
    assert error.stop_collection == stops
    assert "private URL" not in json.dumps(error.details())
    assert classify_ingest_error(error, "other") is error
    if code == "youtube_blocked":
        assert error.retry_after_seconds >= 300
        assert error.retryable and "Captions may still exist" in str(error)


def make_library(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    service = ChatService(config, ScriptedProvider(), Corpus(config))
    history = History(tmp_path / "state.sqlite3")
    return Library(service, history), service, history


def test_block_stops_collection_preserves_library_and_cooldown_across_restart(
    store, video, tmp_path, monkeypatch
):
    library, service, history = make_library(store, video, tmp_path)
    before = store.snapshot_hash()
    calls = []
    request = PlaylistRequest(
        url="https://www.youtube.com/playlist?list=PL1234567890", limit=17, languages=["ru"]
    )
    monkeypatch.setattr(
        "kbfromyt.web.library.enumerate_videos", lambda *_: [f"video{i:06d}" for i in range(17)]
    )

    def blocked(vid, _):
        calls.append(vid)
        raise IpBlocked(vid)

    def forbidden(*_):
        pytest.fail("A fully blocked job must not rewrite sources or the index")

    monkeypatch.setattr("kbfromyt.web.library.fetch_video", blocked)
    monkeypatch.setattr(library, "process", forbidden)
    monkeypatch.setattr(library, "rebuild", forbidden)

    async def scenario():
        library.start(request)
        await library.task
        job = library.job
        assert len(calls) == 1
        assert (job["status"], job["error_code"]) == ("blocked", "youtube_blocked")
        assert (job["completed"], job["failed"], job["skipped"], job["indexed"]) == (1, 1, 16, 0)
        assert job["results"][0]["stage"] == "captions"
        assert job["results"][0]["error_type"] == "IpBlocked"
        assert all(r["status"] == "not_attempted" for r in job["results"][1:])
        assert job["request"] == request.model_dump(mode="json")
        assert not history.playlists()
        assert store.snapshot_hash() == before and service.status()["ready"]
        assert history.jobs()[0] == job
        with pytest.raises(ValueError, match="paused"):
            library.start(request)
        # Cooldown survives even when a job moves outside the ten visible entries.
        for i in range(11):
            history.save_job({"id": f"old-rebuild-{i}", "status": "completed"})
        restarted = Library(service, History(history.path))
        assert restarted.status()["import_retry_not_before"] == job["retry_not_before"]
        with pytest.raises(ValueError, match="paused"):
            restarted.start(request)
        # Local repair remains usable during the download pause.
        restarted.start()
        await restarted.task
        assert restarted.job["status"] == "completed" and service.status()["ready"]
        await service.close()

    asyncio.run(scenario())


def test_block_after_success_indexes_success_and_retains_prior_playlist_members(
    store, video, tmp_path, monkeypatch
):
    library, service, history = make_library(store, video, tmp_path)
    request = PlaylistRequest(url="https://www.youtube.com/playlist?list=PL1234567890")
    history.save_playlist(
        {
            "id": "PL1234567890",
            "title": "Existing title",
            "url": request.url,
            "video_ids": [video.video_id],
        }
    )
    added = video.model_copy(update={"video_id": "newvideo001", "title": "New video"}, deep=True)
    calls = []
    monkeypatch.setattr(
        "kbfromyt.web.library.enumerate_videos",
        lambda *_: [added.video_id, "blocked0001", "skipped0001"],
    )

    def fetch(vid, _):
        calls.append(vid)
        if vid == added.video_id:
            return added
        raise IpBlocked(vid)

    monkeypatch.setattr("kbfromyt.web.library.fetch_video", fetch)

    async def scenario():
        library.start(request)
        await library.task
        job = library.job
        assert calls == [added.video_id, "blocked0001"]
        assert job["status"] == "partial" and job["error_code"] == "youtube_blocked"
        assert (job["indexed"], job["failed"], job["skipped"]) == (1, 1, 1)
        assert [r["status"] for r in job["results"]] == ["indexed", "failed", "not_attempted"]
        playlist = history.playlists()[0]
        assert playlist["video_ids"] == [video.video_id, added.video_id]
        assert playlist["title"] == "Existing title"
        assert set(service.corpus.videos) == {video.video_id, added.video_id}
        assert service.status()["ready"] and library.cooldown_until > time.time()
        assert list((tmp_path / "backups").glob("*.sqlite3"))
        await service.close()

    asyncio.run(scenario())


def test_caption_absence_continues_batch_and_reports_no_usable_captions(
    store, video, tmp_path, monkeypatch
):
    library, service, _ = make_library(store, video, tmp_path)
    calls = []
    monkeypatch.setattr(
        "kbfromyt.web.library.enumerate_videos", lambda *_: ["missing0001", "missing0002"]
    )

    def missing(vid, _):
        calls.append(vid)
        raise TranscriptsDisabled(vid)

    monkeypatch.setattr("kbfromyt.web.library.fetch_video", missing)

    async def scenario():
        library.start(PlaylistRequest(url="https://www.youtube.com/playlist?list=PL1234567890"))
        await library.task
        assert len(calls) == 2
        assert library.job["status"] == "failed"
        assert library.job["error_code"] == "no_usable_captions"
        assert library.job["failed"] == 2 and library.job["skipped"] == 0
        assert all(r["error_code"] == "captions_unavailable" for r in library.job["results"])
        assert service.status()["ready"] and library.cooldown_until == 0
        await service.close()

    asyncio.run(scenario())


def test_expired_pause_allows_manual_retry_with_original_request(
    store, video, tmp_path, monkeypatch
):
    library, service, history = make_library(store, video, tmp_path)
    history.save_job({"id": "expired", "status": "blocked", "retry_not_before": time.time() - 1})
    library = Library(service, history)
    request = PlaylistRequest(url="https://www.youtube.com/playlist?list=PL1234567890")
    monkeypatch.setattr("kbfromyt.web.library.enumerate_videos", lambda *_: [video.video_id])
    monkeypatch.setattr("kbfromyt.web.library.fetch_video", lambda *_: video)

    async def scenario():
        library.start(request)
        await library.task
        assert library.job["status"] == "completed" and library.job["indexed"] == 1
        assert library.job["request"] == request.model_dump(mode="json")
        await service.close()

    asyncio.run(scenario())
