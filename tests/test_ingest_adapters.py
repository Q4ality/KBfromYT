from types import SimpleNamespace

import pytest
import youtube_transcript_api
import yt_dlp

from kbfromyt.ingest import enumerate_videos, fetch_video


class MetadataClient:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def extract_info(self, url, download=False):
        return {
            "title": "Source title",
            "channel": "Source channel",
            "duration": 30,
            "chapters": [{"start_time": 0, "title": "First"}],
        }


def test_youtube_adapter_maps_metadata_and_captions(monkeypatch):
    track = SimpleNamespace(
        language_code="en",
        is_generated=False,
        fetch=lambda: [SimpleNamespace(start=3.5, duration=4, text="Hello.")],
    )
    api = SimpleNamespace(list=lambda vid: [track])
    monkeypatch.setattr(yt_dlp, "YoutubeDL", MetadataClient)
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", lambda: api)
    video = fetch_video("dQw4w9WgXcQ", ["en"])
    assert video.title == "Source title"
    assert video.transcript_source == "manual"
    assert video.segments[0].start == 3.5
    assert video.segments[0].end == 7.5
    assert video.chapters[0].title == "First"


def test_blocked_request_never_triggers_whisper(monkeypatch):
    def blocked(vid):
        raise RuntimeError("blocked request")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", MetadataClient)
    monkeypatch.setattr(
        youtube_transcript_api, "YouTubeTranscriptApi", lambda: SimpleNamespace(list=blocked)
    )
    with pytest.raises(RuntimeError, match="blocked request"):
        fetch_video("dQw4w9WgXcQ", ["en"], whisper=True)


def test_caption_absence_explains_fallback(monkeypatch):
    def missing(vid):
        raise youtube_transcript_api.TranscriptsDisabled(vid)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", MetadataClient)
    monkeypatch.setattr(
        youtube_transcript_api, "YouTubeTranscriptApi", lambda: SimpleNamespace(list=missing)
    )
    with pytest.raises(RuntimeError, match="--whisper"):
        fetch_video("dQw4w9WgXcQ", ["en"])


def test_collection_deduplicates_and_limits(monkeypatch):
    class CollectionClient(MetadataClient):
        def extract_info(self, url, download=False):
            return {
                "entries": [
                    {"id": "dQw4w9WgXcQ"},
                    {"id": "dQw4w9WgXcQ"},
                    None,
                    {"id": "DEMOvideo01"},
                ]
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", CollectionClient)
    assert enumerate_videos("https://youtube.com/playlist?list=TEST", 1) == ["dQw4w9WgXcQ"]
    with pytest.raises(ValueError):
        enumerate_videos("https://example.com/playlist", 2)
