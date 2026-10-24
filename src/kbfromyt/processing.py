from __future__ import annotations

import html
import math
import re

from kbfromyt.models import Chapter, Chunk, ProcessedVideo, Segment, SourceChapter, VideoInput

PROCESSING_VERSION = "lexical-boundaries-v2-clean-cues"

# Only recognized non-speech annotations; arbitrary bracketed speech stays intact.
CAPTION_CUES = frozenset(
    {
        "music",
        "background music",
        "music playing",
        "music fades",
        "instrumental music",
        "applause",
        "clapping",
        "laughter",
        "laughing",
        "silence",
        "inaudible",
        "noise",
        "cheering",
        "музыка",
        "звучит музыка",
        "аплодисменты",
        "смех",
        "тишина",
        "неразборчиво",
        "шум",
        "смеётся",
        "смеются",
    }
)


def clean_caption(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(text))

    def strip_cue(match: re.Match) -> str:
        cue = " ".join(match.group()[1:-1].casefold().split()).strip(" ♪♫")
        return " " if cue in CAPTION_CUES else match.group()

    text = re.sub(r"\[[^\[\]\n]{1,80}\]|\([^()\n]{1,80}\)", strip_cue, text)
    return " ".join(text.replace("♪", " ").replace("♫", " ").split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def process(video: VideoInput, max_words: int = 280, chapter_seconds: int = 300) -> ProcessedVideo:
    if max_words < 10 or chapter_seconds < 1:
        raise ValueError("max_words must be >=10 and chapter_seconds >=1")
    segments = []
    for i, raw in enumerate(video.segments):
        text = clean_caption(raw.text)
        if text:
            segments.append(
                Segment(
                    id=f"{video.video_id}:s{i}",
                    start=raw.start,
                    end=raw.end,
                    text=text,
                    raw_text=raw.text,
                )
            )
    if not segments:
        raise ValueError("transcript contains no text after normalization")
    starts = list(video.chapters)
    if starts:
        if starts[0].start > 0:
            starts.insert(0, SourceChapter(start=0, title="Introduction"))
    else:
        starts = [
            SourceChapter(start=t, title=f"Part {i + 1}")
            for i, t in enumerate(range(0, math.ceil(video.duration), chapter_seconds))
        ]
    chapters, chunks = [], []
    for i, source in enumerate(starts):
        stop = starts[i + 1].start if i + 1 < len(starts) else video.duration
        members = [s for s in segments if source.start <= s.start < stop]
        if not members:
            continue
        chapter = Chapter(
            id=f"{video.video_id}:c{i}",
            video_id=video.video_id,
            title=source.title,
            start=source.start,
            end=max(stop, max(s.end for s in members)),
            source="youtube" if video.chapters else "timed",
            segment_ids=[s.id for s in members],
        )
        chapters.append(chapter)
        group: list[Segment] = []

        def flush(group: list[Segment], chapter: Chapter) -> None:
            if group:
                chunks.append(
                    Chunk(
                        id=f"{video.video_id}:k{len(chunks)}",
                        video_id=video.video_id,
                        chapter_id=chapter.id,
                        start=group[0].start,
                        end=max(s.end for s in group),
                        text=" ".join(s.text for s in group),
                        segment_ids=[s.id for s in group],
                    )
                )
                group.clear()

        for segment in members:
            words = sum(len(s.text.split()) for s in group)
            previous = tokens(" ".join(s.text for s in group[-3:]))
            current = tokens(segment.text)
            drift = previous and len(previous & current) / max(1, len(current)) < 0.08
            boundary = group and (
                words + len(segment.text.split()) > max_words
                or (words >= max_words // 2 and (group[-1].text.endswith((".", "?", "!")) or drift))
            )
            if boundary:
                flush(group, chapter)
            group.append(segment)
        flush(group, chapter)
    return ProcessedVideo(video=video, segments=segments, chapters=chapters, chunks=chunks)
