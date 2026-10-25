import pytest

from kbfromyt.models import RawSegment
from kbfromyt.retrieval import search
from kbfromyt.semantic import SemanticIndex


class TestVectors:
    """Deterministic vectors only verify adapter plumbing, not semantic quality."""

    __test__ = False
    name = "test-vectors-v1"

    def embed(self, texts, *, query=False):
        return [[1.0, float("trajectory" in text.lower()), 0.5] for text in texts]


def test_qdrant_round_trip_and_invalidation(tmp_path, store, video):
    pytest.importorskip("qdrant_client")
    index = SemanticIndex(tmp_path / "vectors", TestVectors())
    try:
        with pytest.raises(ValueError, match="missing/incomplete"):
            index.search(store, "trajectory")
        store.import_video(video)
        assert index.rebuild(store) == store.stats()["documents"]
        assert search(store, "trajectory", semantic=index)
        video.title = "Changed metadata"
        store.import_video(video)
        with pytest.raises(ValueError, match="stale"):
            index.search(store, "trajectory")
        index.rebuild(store)
        index.embedder.name = "different-model"
        with pytest.raises(ValueError, match="model changed"):
            index.search(store, "trajectory")
    finally:
        index.close()


def test_incomplete_rebuild_has_no_manifest(tmp_path, store, video):
    pytest.importorskip("qdrant_client")
    vectors = TestVectors()
    index = SemanticIndex(tmp_path / "vectors", vectors)
    try:
        store.import_video(video)
        index.rebuild(store)
        vectors.embed = lambda texts: []
        with pytest.raises(ValueError, match="incomplete vectors"):
            index.rebuild(store)
        assert not index.manifest.exists()
    finally:
        index.close()


def test_rebuild_reports_batches_and_reuses_exact_current_index(tmp_path, store, video):
    from tests.test_broad_retrieval import WindowVectors

    video.segments = [RawSegment(start=0, end=40, text="source words " * 1000)]
    store.import_video(video)
    index = SemanticIndex(tmp_path / "vectors", WindowVectors())
    events = []
    try:
        index.rebuild(store, progress=lambda *event: events.append(event))
        batches = [(done, total) for stage, done, total in events if stage == "embedding"]
        assert len(batches) > 2 and batches[0][0] == 0
        assert batches[-1][0] == batches[-1][1]
        assert all(a[0] < b[0] for a, b in zip(batches, batches[1:], strict=False))
        assert events[0] == ("preparing", 0, store.stats()["documents"])

        def forbidden(*_):
            pytest.fail("An unchanged index must not recompute embeddings")

        index.embedder.embed = forbidden
        events.clear()
        index.rebuild(store, progress=lambda *event: events.append(event), skip_current=True)
        assert events[-1][0] == "current"
        assert events[-1][1] == events[-1][2] == batches[-1][1]
        assert not any(stage == "embedding" for stage, _, _ in events)
    finally:
        index.close()


@pytest.mark.parametrize("invalid", ["missing_point", "source", "model", "format", "manifest"])
def test_skip_current_rebuilds_incomplete_or_stale_index(tmp_path, store, video, invalid):
    import json

    from qdrant_client import models

    store.import_video(video)
    vectors = TestVectors()
    index = SemanticIndex(tmp_path / "vectors", vectors)
    try:
        index.rebuild(store)
        metadata = json.loads(index.manifest.read_text())
        if invalid == "missing_point":
            points, _ = index.client.scroll("documents", limit=1)
            index.client.delete("documents", models.PointIdsList(points=[points[0].id]), wait=True)
        elif invalid == "source":
            video.title = "New title"
            store.import_video(video)
        elif invalid == "model":
            vectors.name = "changed-model"
        elif invalid == "format":
            metadata["index_version"] = "old"
            index.manifest.write_text(json.dumps(metadata))
        else:
            index.manifest.write_text("invalid JSON")
        events = []
        index.rebuild(store, progress=lambda *event: events.append(event), skip_current=True)
        assert any(stage == "embedding" for stage, _, _ in events)
        assert not any(stage == "current" for stage, _, _ in events)
        assert index.search(store, "trajectory")
    finally:
        index.close()


def test_reuse_prunes_obsolete_points_without_embedding(tmp_path, store, video):
    import json
    from uuid import uuid4

    from qdrant_client import models

    store.import_video(video)
    index = SemanticIndex(tmp_path / "vectors", TestVectors())
    try:
        index.rebuild(store)
        metadata = index.manifest.read_text()
        index.client.upsert(
            "documents",
            [
                models.PointStruct(
                    id=str(uuid4()), vector=[1.0, 0.0, 0.5], payload={"id": "obsolete"}
                )
            ],
            wait=True,
        )
        index.embedder.embed = lambda *_: pytest.fail("Existing vectors must be reused")
        events = []
        index.rebuild(store, progress=lambda *event: events.append(event), skip_current=True)
        assert any(stage == "pruning" for stage, _, _ in events)
        assert events[-1][0] == "current"
        assert index.client.count("documents", exact=True).count == json.loads(metadata)["count"]
        assert json.loads(index.manifest.read_text()) == json.loads(metadata)
    finally:
        index.close()


def test_rebuild_clears_old_points_even_if_directory_removal_fails(
    tmp_path, store, video, monkeypatch
):
    import json

    store.import_video(video)
    index = SemanticIndex(tmp_path / "vectors", TestVectors())
    try:
        index.rebuild(store)
        video.title = "Different length title makes new window IDs"
        store.import_video(video)
        monkeypatch.setattr("qdrant_client.local.qdrant_local.shutil.rmtree", lambda *a, **k: None)
        index.rebuild(store)
        assert (
            index.client.count("documents", exact=True).count
            == json.loads(index.manifest.read_text())["count"]
        )
        assert index.search(store, "trajectory")
    finally:
        index.close()
