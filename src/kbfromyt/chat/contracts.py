from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from kbfromyt.models import Contract

Status = Literal["grounded", "partial", "no_support", "verification_failed", "error"]


class ChatRequest(Contract):
    conversation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    message: str = Field(min_length=1, max_length=8000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    agentic: bool = True

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class SourceRef(Contract):
    source_id: str
    quote: str = Field(min_length=8, max_length=4000)


class DraftClaim(Contract):
    text: str = Field(min_length=1, max_length=1500)
    citations: list[SourceRef] = Field(min_length=1, max_length=4)


class Draft(Contract):
    claims: list[DraftClaim] = Field(max_length=6)
    unanswered: list[str] = Field(max_length=6)


class SupportCheck(Contract):
    supported_claims: list[int]
    missing_parts: list[str]


class AnswerClaim(Contract):
    text: str
    citations: list[str]


class Citation(Contract):
    id: str
    chunk_id: str
    video_id: str
    video_title: str
    chapter_title: str
    start: float
    end: float
    url: str
    excerpt: str
    supporting_quotes: list[str]
    segment_ids: list[str]
    language: str
    transcript_source: str


class Usage(Contract):
    provider_requests: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    memory_turns: int = 0


class RetrievalStep(Contract):
    tool: str
    query: str = ""
    chunk_ids: list[str] = Field(default_factory=list)
    returned_chunk_ids: list[str] = Field(default_factory=list)
    returned_video_ids: list[str] = Field(default_factory=list)


class Coverage(Contract):
    mode: str = "detail"
    library_videos: int = 0
    evidence_videos: int = 0
    evidence_passages: int = 0
    omitted_passages: int = 0


class AnswerEnvelope(Contract):
    retrieval: list[RetrievalStep] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    conversation_id: str | None = None
    reply_id: str = Field(default_factory=lambda: uuid4().hex)
    status: Status
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)
    notice: str = ""
    error_code: str | None = None
    model: str
    usage: Usage = Field(default_factory=Usage)

    def display_text(self) -> str:
        lines = [self.notice] if self.notice else []
        for claim in self.claims:
            lines.append(claim.text + " " + " ".join(f"[{c}]" for c in claim.citations))
        lines.extend(f"Unanswered: {part}" for part in self.unanswered)
        lines.extend(f"[{c.id}] {c.video_title}: {c.url}" for c in self.citations)
        return "\n\n".join(lines)


class SearchArgs(Contract):
    query: str = Field(min_length=1, max_length=1000)
    video_ids_or_null: list[str] | None
    k: int = Field(ge=1, le=8)


class ContextArgs(Contract):
    source_handle: str
    neighbor_count: int = Field(ge=0, le=1)
