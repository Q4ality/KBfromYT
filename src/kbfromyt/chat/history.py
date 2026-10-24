from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from kbfromyt.chat.contracts import AnswerEnvelope


class History:
    """Local durable app state, separate from transcript/index storage."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS conversation_owner ON conversations(owner, updated);
                CREATE TABLE IF NOT EXISTS turns(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation TEXT REFERENCES conversations(id), request TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
                    status TEXT NOT NULL, UNIQUE(conversation, request));
                CREATE TABLE IF NOT EXISTS library_jobs(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS playlists(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def owner(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, owner: str) -> str:
        key = uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations VALUES(?,?,?,?,?)",
                (key, self.owner(owner), "New conversation", now, now),
            )
        return key

    def require(self, owner: str, key: str) -> None:
        with self.connect() as db:
            if not db.execute(
                "SELECT 1 FROM conversations WHERE id=? AND owner=?", (key, self.owner(owner))
            ).fetchone():
                raise KeyError("conversation not found")

    def list(self, owner: str, offset: int = 0) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,title,created,updated FROM conversations WHERE owner=? "
                    "ORDER BY updated DESC, id DESC LIMIT 101 OFFSET ?",
                    (self.owner(owner), max(0, offset)),
                )
            ]

    def page(self, owner: str, key: str, before: int | None = None) -> dict:
        self.require(owner, key)
        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT seq,question,answer FROM turns WHERE conversation=? AND seq<? "
                    "ORDER BY seq DESC LIMIT 101",
                    (key, before or 9223372036854775807),
                )
            )
        return {
            "id": key,
            "has_older": len(rows) > 100,
            "turns": [
                {
                    "seq": row["seq"],
                    "question": row["question"],
                    "answer": AnswerEnvelope.model_validate_json(row["answer"]).model_dump(),
                }
                for row in reversed(rows[:100])
            ],
        }

    def memory(self, owner: str, key: str, count: int) -> list[tuple[str, AnswerEnvelope]]:
        self.require(owner, key)
        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT question,answer FROM turns WHERE conversation=? "
                    "AND status IN ('grounded','partial','no_support') ORDER BY seq DESC LIMIT ?",
                    (key, count),
                )
            )
        return [(row[0], AnswerEnvelope.model_validate_json(row[1])) for row in reversed(rows)]

    def completed(self, key: str, request: str) -> tuple[str, AnswerEnvelope] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT fingerprint,answer FROM turns WHERE conversation=? AND request=?",
                (key, request),
            ).fetchone()
        return (row[0], AnswerEnvelope.model_validate_json(row[1])) if row else None

    def append(
        self, key: str, request: str, fingerprint: str, question: str, answer: AnswerEnvelope
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO turns(conversation,request,fingerprint,question,answer,status) "
                "VALUES(?,?,?,?,?,?)",
                (key, request, fingerprint, question, answer.model_dump_json(), answer.status),
            )
            db.execute(
                "UPDATE conversations SET updated=?, title=CASE WHEN "
                "(SELECT COUNT(*) FROM turns WHERE conversation=?)=1 THEN ? ELSE title END "
                "WHERE id=?",
                (time.time(), key, question[:80], key),
            )

    def save_job(self, job: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO library_jobs VALUES(?,?)",
                (job["id"], json.dumps(job, ensure_ascii=False)),
            )

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT body FROM library_jobs ORDER BY rowid DESC LIMIT 10")
            ]

    def save_playlist(self, playlist: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO playlists VALUES(?,?)",
                (playlist["id"], json.dumps(playlist, ensure_ascii=False)),
            )

    def playlists(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM playlists")]
