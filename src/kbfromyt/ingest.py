from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kbfromyt.models import RawSegment, SourceChapter, VideoInput


def video_id(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    url = urlparse(value)
    if url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ValueError("expected a YouTube URL or an 11-character video ID")
    candidate = (
        url.path.strip("/") if url.hostname == "youtu.be" else parse_qs(url.query).get("v", [""])[0]
    )
    if not candidate and url.path.startswith(("/shorts/", "/embed/", "/live/")):
        candidate = url.path.split("/")[2]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError("URL does not identify a video")
    return candidate


def select_track(tracks: object, languages: list[str]) -> object:
    available = list(tracks)  # type: ignore[call-overload]
    for generated in (False, True):
        for language in languages:
            for track in available:
                if track.language_code == language and track.is_generated == generated:
                    return track
    from youtube_transcript_api import NoTranscriptFound

    raise NoTranscriptFound("unknown", languages, tracks)


def transcribe(audio: Path, model: str = "base") -> list[RawSegment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("install kbfromyt[whisper] to transcribe audio") from exc
    segments, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(str(audio))
    return [
        RawSegment(start=s.start, end=s.end, text=s.text)
        for s in segments
        if s.text.strip() and s.end > s.start
    ]


def fetch_video(
    value: str, languages: list[str], whisper: bool = False, whisper_model: str = "base"
) -> VideoInput:
    import yt_dlp
    from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

    vid = video_id(value)
    url = f"https://www.youtube.com/watch?v={vid}"
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 2,
        }
    ) as client:
        info = client.extract_info(url, download=False)
    if not info:
        raise ValueError("YouTube returned no metadata")
    language = languages[0]
    try:
        track = select_track(YouTubeTranscriptApi().list(vid), languages)
        fetched = track.fetch()
        segments = [
            RawSegment(start=s.start, end=s.start + s.duration, text=s.text)
            for s in fetched
            if s.text.strip() and s.duration > 0
        ]
        source = "auto" if track.is_generated else "manual"
        language = track.language_code
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        if not whisper:
            raise RuntimeError("captions unavailable; use --whisper for audio fallback") from exc
        with tempfile.TemporaryDirectory(prefix="kbfromyt-") as directory:
            with yt_dlp.YoutubeDL(
                {
                    "quiet": True,
                    "format": "bestaudio/best",
                    "outtmpl": str(Path(directory) / "audio.%(ext)s"),
                    "noplaylist": True,
                    "socket_timeout": 20,
                    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
                }
            ) as client:
                client.extract_info(url, download=True)
            segments = transcribe(Path(directory) / "audio.wav", whisper_model)
        source = "whisper"
        language = "und"  # Automatic language detection; no unverified requested-language label.
    if not segments:
        raise ValueError("video has no usable transcript segments")
    return VideoInput(
        video_id=vid,
        title=info.get("title") or vid,
        channel=info.get("channel") or "",
        language=language,
        published_at=info.get("upload_date"),
        transcript_source=source,
        duration=max(float(info.get("duration") or 0), max(s.end for s in segments)),
        segments=segments,
        chapters=[
            SourceChapter(start=c["start_time"], title=c["title"])
            for c in info.get("chapters") or []
        ],
    )


def enumerate_videos(url: str, limit: int) -> list[str]:
    import yt_dlp

    if limit < 1:
        raise ValueError("limit must be positive")
    parsed = urlparse(url)
    if parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        raise ValueError("expected a YouTube playlist or channel URL")
    with yt_dlp.YoutubeDL(
        {"quiet": True, "extract_flat": "in_playlist", "playlistend": limit, "socket_timeout": 20}
    ) as client:
        info = client.extract_info(url, download=False)
    return list(
        dict.fromkeys(
            video_id(e["id"]) for e in (info or {}).get("entries", []) if e and e.get("id")
        )
    )[:limit]
