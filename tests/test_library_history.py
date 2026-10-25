import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest
from kbfromyt.chat.history import History
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.models import RawSegment
from kbfromyt.processing import clean_caption, process
from kbfromyt.web.app import create_app
from kbfromyt.web.library import Library, PlaylistRequest
from tests.test_chat import ScriptedProvider


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello [Music] world [APPLAUSE]", "Hello world"),
        ("[музыка] Слова [аплодисменты]", "Слова"),
        ("♪ sung words ♫ (laughter)", "sung words"),
        (
            "[Music theory] is a title [1943] [speaker 1]",
            "[Music theory] is a title [1943] [speaker 1]",
        ),
        ("[МуЗыКа] [ смех ]", ""),
        ("&lt;i&gt;A&lt;/i&gt; &amp; [music] B", "A & B"),
    ],
)
def test_known_audio_cues_only(text, expected):
    assert clean_caption(text) == expected


def test_cleaning_retains_raw_positions_and_migrates_once(video, store):
    video.segments = [
        RawSegment(start=0, end=2, text="[music]"),
        RawSegment(start=2, end=6, text="Speech [applause] continues"),
        RawSegment(start=6, end=8, text="[A real aside]"),
    ]
    derived = process(video)
    assert [s.id for s in derived.segments] == [f"{video.video_id}:s1", f"{video.video_id}:s2"]
    assert derived.segments[0].raw_text == "Speech [applause] continues"
    assert derived.chunks[0].start == 2
    assert derived.video.segments[0].text == "[music]"
    store.import_video(video)
    store.db.execute("UPDATE videos SET hash='legacy'")
    store.db.commit()
    assert store.needs_reprocessing()
    assert store.reprocess() == 1
    assert not store.needs_reprocessing() and store.reprocess() == 0
    assert store.videos()[0].video == video
    assert not store.lexical("music", "chunk")


def test_saved_chats_restore_only_three_pairs_and_deduplicate_after_restart(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False, memory_budget=12000)
    history = History(tmp_path / "state.sqlite3")

    async def scenario():
        service = ChatService(config, ScriptedProvider(), Corpus(config), history=history)
        key, cid = None, None
        for number in range(5):
            key, reply = await service.chat(
                key,
                ChatRequest(
                    message=f"Question {number}",
                    request_id=f"request_{number}",
                    conversation_id=cid,
                ),
                "browser-one",
            )
            cid = reply.conversation_id
            assert reply.usage.memory_turns == min(number, 3)
        first_reply = reply.reply_id
        await service.close()
        provider = ScriptedProvider()
        restored = ChatService(config, provider, Corpus(config), history=History(history.path))
        _, repeated = await restored.chat(
            None,
            ChatRequest(message="Question 4", request_id="request_4", conversation_id=cid),
            "browser-one",
        )
        assert repeated.reply_id == first_reply and not provider.requests
        _, reply = await restored.chat(
            None,
            ChatRequest(message="Follow up", request_id="follow_up", conversation_id=cid),
            "browser-one",
        )
        assert reply.usage.memory_turns == 3
        users = [
            item["content"] for item in provider.requests[0]["items"] if item.get("role") == "user"
        ]
        assert users == ["Question 2", "Question 3", "Question 4", "Follow up"]
        assert len(history.page("browser-one", cid)["turns"]) == 6
        with pytest.raises(KeyError):
            await restored.chat(
                None,
                ChatRequest(
                    message="Other browser", request_id="other_browser", conversation_id=cid
                ),
                "browser-two",
            )
        await restored.close()

    asyncio.run(scenario())


def test_saved_history_pagination_and_owner_isolation(tmp_path):
    history = History(tmp_path / "state.sqlite3")
    key = history.create("one")
    for number in range(105):
        history.append(
            key,
            str(number),
            str(number),
            f"Question {number}",
            AnswerEnvelope(status="no_support", model="fixture"),
        )
    page = history.page("one", key)
    older = history.page("one", key, page["turns"][0]["seq"])
    assert page["has_older"] and len(page["turns"]) == 100
    assert not older["has_older"] and len(older["turns"]) == 5
    assert len({t["seq"] for t in older["turns"] + page["turns"]}) == 105
    assert not history.list("two")
    with pytest.raises(KeyError):
        history.page("two", key)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/playlist?list=PL1234567890",
        "http://youtube.com/playlist?list=PL1234567890",
        "https://youtube.com/playlist?list=short",
        "https://youtube.com/redirect?list=PL1234567890",
    ],
)
def test_playlist_boundary_rejects_non_playlist_targets(url):
    with pytest.raises(ValidationError):
        PlaylistRequest(url=url)


def test_playlist_job_partial_progress_maintenance_and_index_refresh(
    store, video, tmp_path, monkeypatch
):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    service = ChatService(config, ScriptedProvider(), Corpus(config))
    history = History(tmp_path / "state.sqlite3")
    library = Library(service, history)
    request = PlaylistRequest(url="https://www.youtube.com/watch?v=abcdefghijk&list=PL1234567890")
    monkeypatch.setattr(
        "kbfromyt.web.library.enumerate_videos", lambda *_: [video.video_id, "abcdefghijk"]
    )

    def fetch(vid, languages):
        if vid != video.video_id:
            raise RuntimeError("network failure")
        updated = video.model_copy(deep=True)
        updated.title = "Updated playlist video"
        return updated

    monkeypatch.setattr("kbfromyt.web.library.fetch_video", fetch)

    async def scenario():
        job = library.start(request)
        assert job["status"] == "queued" and not service.status()["ready"]
        with pytest.raises(ValueError, match="already"):
            library.start(request)
        _, reply = await service.chat(None, ChatRequest(message="test", request_id="request_1"))
        assert reply.error_code == "maintenance"
        await library.task
        assert library.job["status"] == "partial" and library.job["failed"] == 1
        assert library.job["results"][0]["status"] == "indexed"
        assert service.status()["ready"]
        assert service.corpus.videos[video.video_id].video.title == "Updated playlist video"
        assert history.playlists()[0]["url"] == "https://www.youtube.com/playlist?list=PL1234567890"
        assert list((tmp_path / "backups").glob("*.sqlite3"))
        await library.close()
        await service.close()

    asyncio.run(scenario())


def test_index_failure_exposes_repair_and_interrupted_jobs(store, video, tmp_path, monkeypatch):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    service = ChatService(config, ScriptedProvider(), Corpus(config))
    history = History(tmp_path / "state.sqlite3")
    history.save_job({"id": "old", "status": "indexing"})
    library = Library(service, history)
    assert history.jobs()[0]["status"] == "failed"
    real_rebuild = service.corpus.rebuild

    def fail(**_):
        raise RuntimeError("index failed")

    async def scenario():
        monkeypatch.setattr(service.corpus, "rebuild", fail)
        library.start()
        await library.task
        assert library.job["status"] == "failed" and not service.status()["ready"]
        monkeypatch.setattr(service.corpus, "rebuild", real_rebuild)
        library.start()
        await library.task
        assert library.job["status"] == "completed" and service.status()["ready"]
        await service.close()

    asyncio.run(scenario())


def test_library_persists_index_progress_and_reuses_current_vectors(
    store, video, tmp_path, monkeypatch
):
    from kbfromyt.semantic import SemanticIndex
    from tests.test_semantic import TestVectors

    store.import_video(video)
    config = ChatConfig(
        db=tmp_path / "kb.sqlite3",
        index_dir=tmp_path / "vectors",
        embedding_model=TestVectors.name,
    )
    with_index = SemanticIndex(config.index_dir, TestVectors())
    with_index.rebuild(store)
    with_index.close()
    monkeypatch.setattr("kbfromyt.chat.tools.FastEmbedder", lambda _: TestVectors())
    service = ChatService(config, ScriptedProvider(), Corpus(config))
    history = History(tmp_path / "state.sqlite3")
    library = Library(service, history)
    events = []
    save = history.save_job

    def record(job):
        save(job)
        if job.get("index_stage"):
            events.append((job["index_stage"], job["index_completed"], job["index_total"]))

    monkeypatch.setattr(history, "save_job", record)

    async def scenario():
        # A changed source really rebuilds, with persisted batch completion.
        video.title = "Updated source"
        store.import_video(video)
        library.start()
        await library.task
        assert library.job["status"] == "completed"
        assert any(stage == "embedding" and done == total > 0 for stage, done, total in events)
        assert history.jobs()[0]["finished"] >= library.job["created"]
        # Repeating maintenance verifies IDs without running the embedder.
        service.corpus.semantic.embedder.embed = lambda *_: pytest.fail("Unexpected embedding")
        library.start()
        await library.task
        job = history.jobs()[0]
        assert job["status"] == "completed" and job["index_reused"]
        assert job["index_stage"] == "current" and job["index_completed"] == job["index_total"]
        assert "no embeddings recomputed" in job["message"]
        assert service.status()["ready"]
        await service.close()

    asyncio.run(scenario())


def test_conversation_api_cookies_reopen_and_new_chat_preserves_history(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    service = ChatService(
        config, ScriptedProvider(), Corpus(config), history=History(tmp_path / "state.sqlite3")
    )
    with TestClient(create_app(config, service)) as client:
        assert client.get("/api/conversations").json()["conversations"] == []
        reply = client.post(
            "/api/chat", json={"message": "trajectory", "request_id": "request_1"}
        ).json()
        cid = reply["conversation_id"]
        assert (
            cid
            and client.get(f"/api/conversations/{cid}").json()["turns"][0]["answer"]["citations"]
        )
        client.post("/api/chat/reset")
        assert client.get("/api/conversations").json()["conversations"][0]["id"] == cid
        owner = client.cookies.get("kb_owner")
        client.cookies.clear()
        assert client.get(f"/api/conversations/{cid}").status_code == 404
        client.cookies.set("kb_owner", owner)
        assert client.get(f"/api/conversations/{cid}").status_code == 200
        assert client.get("/api/library").json()["videos"][0]["id"] == video.video_id
