from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from kbfromyt.models import Document, ProcessedVideo, VideoInput
from kbfromyt.processing import PROCESSING_VERSION, process, tokens


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO settings VALUES('revision', '0');
            CREATE TABLE IF NOT EXISTS videos(
                id TEXT PRIMARY KEY, hash TEXT NOT NULL,
                raw TEXT NOT NULL, processed TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                level TEXT NOT NULL, body TEXT NOT NULL, json TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                id UNINDEXED, level UNINDEXED, body, tokenize='unicode61');
        """)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    @property
    def revision(self) -> str:
        return self.db.execute("SELECT value FROM settings WHERE key='revision'").fetchone()[0]

    def import_video(self, video: VideoInput) -> bool:
        raw = video.model_dump_json()
        digest = hashlib.sha256((PROCESSING_VERSION + raw).encode()).hexdigest()
        old = self.db.execute("SELECT hash FROM videos WHERE id=?", (video.video_id,)).fetchone()
        if old and old[0] == digest:
            return False
        processed = process(video)
        docs = self.make_documents(processed)
        with self.db:
            self.db.execute(
                "DELETE FROM documents_fts WHERE id IN (SELECT id FROM documents WHERE video_id=?)",
                (video.video_id,),
            )
            self.db.execute("DELETE FROM videos WHERE id=?", (video.video_id,))
            self.db.execute(
                "INSERT INTO videos VALUES(?,?,?,?)",
                (video.video_id, digest, raw, processed.model_dump_json()),
            )
            for doc in docs:
                self.db.execute(
                    "INSERT INTO documents VALUES(?,?,?,?,?)",
                    (doc.id, doc.video_id, doc.level, doc.text, doc.model_dump_json()),
                )
                self.db.execute(
                    "INSERT INTO documents_fts VALUES(?,?,?)", (doc.id, doc.level, doc.text)
                )
            self.db.execute(
                "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
            )
        return True

    def needs_reprocessing(self) -> bool:
        return any(
            digest != hashlib.sha256((PROCESSING_VERSION + raw).encode()).hexdigest()
            for digest, raw in self.db.execute("SELECT hash, raw FROM videos")
        )

    def reprocess(self) -> int:
        originals = [
            VideoInput.model_validate_json(row[0])
            for row in self.db.execute("SELECT raw FROM videos ORDER BY id")
        ]
        return sum(self.import_video(video) for video in originals)

    @staticmethod
    def make_documents(p: ProcessedVideo) -> list[Document]:
        docs = [
            Document(
                id=f"{p.video.video_id}:video",
                video_id=p.video.video_id,
                level="video",
                start=0,
                end=p.video.duration,
                text=p.video.title + " " + " ".join(s.text for s in p.segments),
            )
        ]
        for chapter in p.chapters:
            docs.append(
                Document(
                    id=chapter.id,
                    video_id=chapter.video_id,
                    chapter_id=chapter.id,
                    level="chapter",
                    start=chapter.start,
                    end=chapter.end,
                    text=chapter.title
                    + " "
                    + " ".join(c.text for c in p.chunks if c.chapter_id == chapter.id),
                )
            )
        for chunk in p.chunks:
            docs.append(
                Document(
                    id=chunk.id,
                    video_id=chunk.video_id,
                    chapter_id=chunk.chapter_id,
                    level="chunk",
                    start=chunk.start,
                    end=chunk.end,
                    text=chunk.text,
                )
            )
        return docs

    def videos(self) -> list[ProcessedVideo]:
        return [
            ProcessedVideo.model_validate_json(row[0])
            for row in self.db.execute("SELECT processed FROM videos ORDER BY id")
        ]

    def documents(self) -> list[Document]:
        return [
            Document.model_validate_json(row[0])
            for row in self.db.execute("SELECT json FROM documents ORDER BY id")
        ]

    def lexical(
        self, query: str, level: str, limit: int = 20, video_ids: list[str] | None = None
    ) -> list[str]:
        terms = sorted(tokens(query))[:64]
        if not terms:
            return []
        literal = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        clause, params = "", []
        if video_ids is not None:
            if not video_ids:
                return []
            clause = (
                " AND id IN (SELECT id FROM documents WHERE video_id IN ("
                + ",".join("?" for _ in video_ids)
                + "))"
            )
            params = video_ids
        rows = self.db.execute(
            "SELECT id FROM documents_fts WHERE documents_fts MATCH ? "
            "AND level=?" + clause + " ORDER BY bm25(documents_fts), id LIMIT ?",
            (literal, level, *params, limit),
        )
        return [row[0] for row in rows]

    def stats(self) -> dict:
        return {
            "videos": self.db.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
            "documents": self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "revision": self.revision,
        }

    def snapshot_hash(self) -> str:
        rows = list(self.db.execute("SELECT id, hash FROM videos ORDER BY id"))
        return hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()
