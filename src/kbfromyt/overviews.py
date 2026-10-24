from __future__ import annotations

import math
import re
from collections import Counter

from kbfromyt.models import Contract, ProcessedVideo
from kbfromyt.processing import tokens

OVERVIEW_VERSION = "extractive-overviews-v1"
STOPWORDS = frozenset(
    """the a an of to in on and or is are was were who what why how
это этот эта эти как что кто где когда для при или они она оно его уже был были есть
так вот все ещё еще мне вам нас вас здесь там чтобы потому только очень который
которые которой автор видео выпуск серии сказал говорит этому этого также значит
чем нам него него себя будет может быть нет да раз под над про если после перед""".split()
)
ARGUMENT = re.compile(
    r"счита\w*|полага\w*|основан\w*|вывод\w*|утвержд\w*|доказ\w*|"
    r"противореч\w*|верси\w*|таким образом|следовательно|"
    r"\bargu\w*|\bconclu\w*|\bevidence\b|\bclaim\w*|\btherefore\b",
    re.I,
)


def content_terms(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) > 2 and t not in STOPWORDS}


class OverviewPassage(Contract):
    chunk_id: str
    chapter_title: str
    start: float
    end: float
    excerpt: str
    url: str
    segment_ids: list[str]


class VideoOverview(Contract):
    version: str = OVERVIEW_VERSION
    video_id: str
    title: str
    channel: str
    method: str = "extractive"
    topics: list[str]
    passages: list[OverviewPassage]


def build_overview(video: ProcessedVideo, count: int = 6) -> VideoOverview:
    """Extract representative source passages; never generate or adjudicate claims."""
    frequency = Counter(t for chunk in video.chunks for t in content_terms(chunk.text))
    chapters = {chapter.id: chapter.title for chapter in video.chapters}

    def score(chunk):
        words = content_terms(chunk.text)
        centrality = sum(math.log1p(frequency[t]) for t in words) / max(1, len(words))
        return centrality + min(6, len(ARGUMENT.findall(chunk.text))) * 0.35

    selected = []
    # Sample the entire timeline rather than treating the introduction as a summary.
    for band in range(min(count, len(video.chunks))):
        candidates = [
            c
            for c in video.chunks
            if min(count - 1, int(c.start / video.video.duration * count)) == band
        ]
        if candidates:
            selected.append(max(candidates, key=lambda c: (score(c), -c.start)))
    for chunk in sorted(video.chunks, key=lambda c: (-score(c), c.start)):
        if len(selected) >= count:
            break
        if chunk not in selected:
            selected.append(chunk)
    return VideoOverview(
        video_id=video.video.video_id,
        title=video.video.title,
        channel=video.video.channel,
        topics=list(dict.fromkeys(c.title for c in video.chapters)),
        passages=[
            OverviewPassage(
                chunk_id=c.id,
                chapter_title=chapters[c.chapter_id],
                start=c.start,
                end=c.end,
                excerpt=c.text,
                segment_ids=c.segment_ids,
                url=f"https://www.youtube.com/watch?v={c.video_id}&t={math.floor(c.start)}s",
            )
            for c in sorted(selected, key=lambda c: c.start)
        ],
    )


def broad_question(question: str) -> bool:
    return bool(
        re.search(
            r"overview|overall|across.*videos|series.*about|responsib|"
            r"who.*(?:kill|murder)|what.*(?:author|argue|version|videos)|"
            r"кто.*(?:убил|убий|расстрел|ответствен|винов)|"
            r"(?:позици|общий|основн|главн|официальн).*(?:автор|вывод|верси|аргумент|тема)|"
            r"(?:какие|каковы).*(?:доказательств|аргумент|версии|выводы)|о чём.*(?:видео|серия)",
            question,
            re.I,
        )
    )
