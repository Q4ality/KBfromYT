import pytest

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
