from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from kbfromyt.chat.contracts import AnswerEnvelope, SourceScope


class History:
    """Local durable app state, separate from transcript/index storage."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise RuntimeError(
                    "App state uses a newer schema. Use the matching application version."
                )
            columns = {row[1] for row in db.execute("PRAGMA table_info(conversations)")}
            requests_exist = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='chat_requests'"
            ).fetchone()
            if columns and ("scope" not in columns or not requests_exist):
                backups = path.parent / "backups"
                backups.mkdir(exist_ok=True)
                with sqlite3.connect(
                    backups / f"before-{path.stem}-chat-scope-{time.time_ns()}.sqlite3"
                ) as target:
                    db.backup(target)
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
            if "scope" not in {row[1] for row in db.execute("PRAGMA table_info(conversations)")}:
                db.execute("ALTER TABLE conversations ADD COLUMN scope TEXT NOT NULL DEFAULT '{}'")
            db.execute("""CREATE TABLE IF NOT EXISTS chat_requests(
                owner TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL,
                conversation TEXT NOT NULL REFERENCES conversations(id), state TEXT NOT NULL,
                answer TEXT, updated REAL NOT NULL, PRIMARY KEY(owner,request))""")
            db.execute("PRAGMA user_version=2")

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

    def create(self, owner: str, scope: SourceScope | None = None) -> str:
        key = uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(id,owner,title,created,updated,scope) "
                "VALUES(?,?,?,?,?,?)",
                (
                    key,
                    self.owner(owner),
                    "New conversation",
                    now,
                    now,
                    (scope or SourceScope()).model_dump_json(),
                ),
            )
        return key

    def scope(self, owner: str, key: str) -> SourceScope:
        self.require(owner, key)
        with self.connect() as db:
            value = db.execute("SELECT scope FROM conversations WHERE id=?", (key,)).fetchone()[0]
        return SourceScope.model_validate_json(value)

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
            "scope": self.scope(owner, key).model_dump(),
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

    def import_cooldown(self) -> float:
        # A local rebuild may move a blocked job outside the ten visible entries.
        with self.connect() as db:
            return max(
                (
                    json.loads(row[0]).get("retry_not_before", 0)
                    for row in db.execute("SELECT body FROM library_jobs")
                ),
                default=0,
            )

    def save_playlist(self, playlist: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO playlists VALUES(?,?)",
                (playlist["id"], json.dumps(playlist, ensure_ascii=False)),
            )

    def playlists(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM playlists")]

    def interrupt_running(self) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE chat_requests SET state='interrupted',updated=? "
                "WHERE state IN ('queued','running')",
                (time.time(),),
            )

    def request(self, owner: str, request_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM chat_requests WHERE owner=? AND request=?",
                (self.owner(owner), request_id),
            ).fetchone()
        return dict(row) if row else None

    def claim(
        self,
        owner: str,
        request_id: str,
        fingerprint: str,
        scope: SourceScope,
        conversation: str | None,
    ) -> dict:
        """Persist identity and first conversation atomically, before provider work."""
        owner_hash, now = self.owner(owner), time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM chat_requests WHERE owner=? AND request=?", (owner_hash, request_id)
            ).fetchone()
            if row:
                if row["fingerprint"] != fingerprint or (
                    conversation and conversation != row["conversation"]
                ):
                    raise ValueError("request_conflict")
                return {**dict(row), "created": False}
            if conversation:
                row = db.execute(
                    "SELECT scope FROM conversations WHERE id=? AND owner=?",
                    (conversation, owner_hash),
                ).fetchone()
                if not row:
                    raise KeyError("conversation not found")
                if SourceScope.model_validate_json(row["scope"]) != scope:
                    raise ValueError("scope_conflict")
            else:
                conversation = uuid4().hex
                db.execute(
                    "INSERT INTO conversations(id,owner,title,created,updated,scope) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        conversation,
                        owner_hash,
                        "New conversation",
                        now,
                        now,
                        scope.model_dump_json(),
                    ),
                )
            db.execute(
                "INSERT INTO chat_requests VALUES(?,?,?,?,?,?,?)",
                (owner_hash, request_id, fingerprint, conversation, "queued", None, now),
            )
        return {"conversation": conversation, "state": "queued", "created": True}

    def request_state(self, owner: str, request_id: str, state: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE chat_requests SET state=?,updated=? WHERE owner=? AND request=?",
                (state, time.time(), self.owner(owner), request_id),
            )

    def finish_request(
        self, owner: str, request_id: str, fingerprint: str, question: str, reply: AnswerEnvelope
    ) -> None:
        """The recovered result and saved turn commit together."""
        state = (
            "interrupted"
            if reply.status == "error" and reply.usage.provider_requests
            else "completed"
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO turns(conversation,request,fingerprint,question,answer,status) "
                "VALUES(?,?,?,?,?,?)",
                (
                    reply.conversation_id,
                    request_id,
                    fingerprint,
                    question,
                    reply.model_dump_json(),
                    reply.status,
                ),
            )
            db.execute(
                "UPDATE conversations SET updated=?,title=CASE WHEN "
                "(SELECT COUNT(*) FROM turns WHERE conversation=?)=1 THEN ? "
                "ELSE title END WHERE id=?",
                (time.time(), reply.conversation_id, question[:80], reply.conversation_id),
            )
            db.execute(
                "UPDATE chat_requests SET state=?,answer=?,updated=? WHERE owner=? AND request=?",
                (state, reply.model_dump_json(), time.time(), self.owner(owner), request_id),
            )
