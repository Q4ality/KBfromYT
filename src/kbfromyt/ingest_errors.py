"""Safe ingestion errors; upstream exception strings can contain signed URLs."""

from __future__ import annotations


class IngestError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str = "captions",
        retryable: bool = False,
        stop_collection: bool = False,
        retry_after_seconds: int = 0,
    ):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.stop_collection = stop_collection
        self.retry_after_seconds = retry_after_seconds

    def details(self) -> dict:
        return {
            "error_code": self.code,
            "stage": self.stage,
            "message": str(self),
            "retryable": self.retryable,
        }


def classify_ingest_error(exc: Exception, stage: str = "captions") -> IngestError:
    if isinstance(exc, IngestError):
        return exc
    from requests import ConnectionError, Timeout
    from youtube_transcript_api import NoTranscriptFound, RequestBlocked, TranscriptsDisabled
    from yt_dlp.utils import DownloadError

    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, RequestBlocked) or status == 429:
        return IngestError(
            "youtube_blocked",
            "YouTube is blocking or rate-limiting subtitle "
            "downloads from this connection. Captions may still exist. Pause before retrying; "
            "YouTube may require a longer wait. Existing indexed videos remain available.",
            stage=stage,
            retryable=True,
            stop_collection=True,
            retry_after_seconds=300,
        )
    if isinstance(exc, NoTranscriptFound):
        return IngestError(
            "caption_language_unavailable",
            "No captions matched the requested "
            "languages. Choose an available caption language and retry.",
            stage=stage,
        )
    if isinstance(exc, TranscriptsDisabled):
        return IngestError(
            "captions_unavailable",
            "YouTube reports no available captions for "
            "this video. Optional audio transcription requires explicit --whisper setup.",
            stage=stage,
        )
    if isinstance(exc, Timeout):
        return IngestError(
            "network_timeout",
            "The YouTube request timed out. Check the connection and retry later.",
            stage=stage,
            retryable=True,
        )
    if isinstance(exc, ConnectionError):
        return IngestError(
            "network_error",
            "Could not connect to YouTube. Check the connection before retrying.",
            stage=stage,
            retryable=True,
            stop_collection=True,
            retry_after_seconds=30,
        )
    if stage == "listing":
        return IngestError(
            "playlist_unavailable",
            "The YouTube playlist could not be listed. "
            "Check that it is accessible and retry later.",
            stage=stage,
            retryable=True,
        )
    if isinstance(exc, DownloadError):
        return IngestError(
            "metadata_unavailable",
            "YouTube video metadata could not be retrieved. "
            "Check whether the video is accessible in your browser.",
            stage="metadata",
            retryable=True,
        )
    if stage == "indexing":
        return IngestError(
            "index_update_failed",
            "Index update failed. Use Clean and rebuild to repair the library.",
            stage=stage,
            retryable=True,
        )
    if isinstance(exc, ValueError):
        return IngestError(
            "invalid_transcript",
            "The downloaded transcript or timestamps could "
            "not be validated. This video was not imported.",
            stage=stage,
        )
    return IngestError(
        "ingestion_failed",
        "The video could not be imported. Retry after checking "
        "its metadata and caption availability.",
        stage=stage,
        retryable=True,
    )
