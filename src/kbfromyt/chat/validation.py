from __future__ import annotations

import re

from kbfromyt.chat.contracts import (
    AnswerClaim,
    AnswerEnvelope,
    Citation,
    Draft,
    Status,
    SupportCheck,
)
from kbfromyt.chat.tools import EvidenceRegistry

NOTICES = {
    "en": {
        "no_support": (
            "The retrieved passages did not provide sufficient supporting citations. "
            "I cannot give a source-grounded answer from these results. "
            "Relevant evidence may exist elsewhere in the library."
        ),
        "partial": "Only part of this question is supported by the indexed videos.",
        "verification_failed": "The answer could not be verified against the retrieved sources.",
    },
    "ru": {
        "no_support": (
            "В найденных фрагментах недостаточно подтверждающих цитат для ответа. "
            "Это не означает, что нужных сведений нет в других частях библиотеки."
        ),
        "partial": "Только часть вопроса подтверждается источниками из проиндексированных видео.",
        "verification_failed": "Не удалось проверить ответ по найденным источникам.",
    },
}


def language(question: str) -> str:
    return "ru" if re.search("[а-яА-ЯёЁ]", question) else "en"


def notice(status: Status, question: str) -> str:
    return NOTICES[language(question)].get(status, "")


def validate_draft(draft: Draft, registry: EvidenceRegistry) -> None:
    for claim in draft.claims:
        for ref in claim.citations:
            source = registry.sources.get(ref.source_id)
            if not source or ref.quote not in source.evidence.text:
                raise ValueError("unknown citation or nonliteral excerpt")
            e = source.evidence
            if e.video_id not in registry.allowed:
                raise ValueError("citation is outside the selected chat scope")
            p = registry.corpus.videos[e.video_id]
            raw = {s.id: s for s in p.segments}
            chunk = next(c for c in p.chunks if c.id == e.id)
            if (
                e.text != chunk.text
                or e.segment_ids != chunk.segment_ids
                or e.start != raw[e.segment_ids[0]].start
                or e.end != max(raw[s].end for s in e.segment_ids)
            ):
                raise ValueError("source provenance or time bounds differ")


def render(
    draft: Draft, check: SupportCheck, registry: EvidenceRegistry, question: str, model: str
) -> AnswerEnvelope:
    accepted = set(check.supported_claims)
    if any(i < 0 or i >= len(draft.claims) for i in accepted):
        raise ValueError("invalid support assessment")
    claims = [claim for i, claim in enumerate(draft.claims) if i in accepted]
    unanswered = list(dict.fromkeys([*draft.unanswered, *check.missing_parts]))
    rejected = len(claims) != len(draft.claims)
    status = "no_support" if not claims else "partial" if unanswered or rejected else "grounded"
    cards = {}
    for claim in claims:
        for ref in claim.citations:
            source = registry.sources[ref.source_id]
            e = source.evidence
            if ref.source_id not in cards:
                cards[ref.source_id] = Citation(
                    id=ref.source_id,
                    chunk_id=e.id,
                    video_id=e.video_id,
                    video_title=e.video_title,
                    chapter_title=e.chapter_title,
                    start=e.start,
                    end=e.end,
                    url=e.url,
                    excerpt=e.text,
                    supporting_quotes=[],
                    segment_ids=e.segment_ids,
                    language=source.language,
                    transcript_source=source.origin,
                )
            if ref.quote not in cards[ref.source_id].supporting_quotes:
                cards[ref.source_id].supporting_quotes.append(ref.quote)
    if rejected and claims and not unanswered:
        unanswered = [
            "Some requested details could not be verified."
            if language(question) == "en"
            else "Часть запрошенных сведений не удалось подтвердить."
        ]
    return AnswerEnvelope(
        status=status,
        model=model,
        notice=notice(status, question),
        claims=[
            AnswerClaim(
                text=c.text, citations=list(dict.fromkeys(r.source_id for r in c.citations))
            )
            for c in claims
        ],
        citations=list(cards.values()),
        unanswered=unanswered,
    )
