from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Interval(Contract):
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class RawSegment(Interval):
    text: str = Field(min_length=1)


class Segment(RawSegment):
    id: str
    raw_text: str


class SourceChapter(Contract):
    start: float = Field(ge=0)
    title: str = Field(min_length=1)


class VideoInput(Contract):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(min_length=1)
    channel: str = ""
    published_at: str | None = None
    language: str = "en"
    duration: float = Field(gt=0)
    transcript_source: Literal["manual", "auto", "whisper", "import"] = "import"
    segments: list[RawSegment] = Field(min_length=1)
    chapters: list[SourceChapter] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_timeline(self) -> Self:
        if any(s.end > self.duration + 0.01 for s in self.segments):
            raise ValueError("segment extends beyond video duration")
        starts = [c.start for c in self.chapters]
        if starts != sorted(set(starts)) or any(s >= self.duration for s in starts):
            raise ValueError("chapter starts must be unique, ascending and inside video")
        if any(a.start > b.start for a, b in zip(self.segments, self.segments[1:], strict=False)):
            raise ValueError("segments must be ordered by start")
        return self


class Chapter(Interval):
    id: str
    video_id: str
    title: str
    source: Literal["youtube", "timed"]
    segment_ids: list[str]


class Chunk(Interval):
    id: str
    video_id: str
    chapter_id: str
    text: str
    segment_ids: list[str]


class ProcessedVideo(Contract):
    video: VideoInput
    segments: list[Segment]
    chapters: list[Chapter]
    chunks: list[Chunk]


class Document(Interval):
    id: str
    video_id: str
    chapter_id: str | None = None
    level: Literal["video", "chapter", "chunk"]
    text: str


class Evidence(Chunk):
    video_title: str
    chapter_title: str
    score: float
    context: list[str] = Field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}&t={math.floor(self.start)}s"

    def as_dict(self) -> dict:
        return {**self.model_dump(), "url": self.url}
