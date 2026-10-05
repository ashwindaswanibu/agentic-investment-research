import numpy as np
import pytest

from researchdesk.data import DataError, retrieve

DOCS = [
    {
        "id": "clinical",
        "title": "Trial research",
        "content": "Randomized efficacy endpoint trial results",
        "sha256": "first",
    },
    {
        "id": "quant",
        "title": "Strategy experiment",
        "content": "Walk forward backtest transaction costs",
        "sha256": "second",
    },
]


def test_lexical_retrieval_returns_attributable_relevant_passages():
    result = retrieve("transaction costs backtest", DOCS)
    assert result["mode"] == "lexical"
    assert result["items"][0]["artifact_id"] == "quant"
    assert result["items"][0]["artifact_sha256"] == "second"
    assert result["items"][0]["start_char"] == 0
    assert result["items"][0]["score"] > 0
    assert len(result["items"][0]["chunk_sha256"]) == 64
    assert retrieve("unrelatedword", DOCS)["items"] == []


def test_chunk_offsets_reconstruct_original_and_hits_can_be_late_in_document():
    text = "a " * 2000 + "biomarker endpoint " * 20
    result = retrieve("biomarker", [{"id": "long", "content": text}])
    match = result["items"][0]
    assert match["start_char"] > 0
    assert text[match["start_char"] : match["end_char"]] == match["text"]


def test_dense_cosine_search_uses_actual_vectors_and_declares_mode():
    class Encoder:
        def passage_embed(self, texts):
            return [np.array([1.0, 0.0]), np.array([0.0, 1.0])]

        def query_embed(self, query):
            return [np.array([0.0, 2.0])]

    result = retrieve("quantitative experiment", DOCS, mode="dense", encoder=Encoder())
    assert result["mode"] == "dense"
    assert result["items"][0]["artifact_id"] == "quant"
    assert result["items"][0]["score"] == pytest.approx(1)
    assert result["score_semantics"] == "cosine similarity"


@pytest.mark.parametrize("vector", [[0.0, 0.0], [float("nan"), 1.0]])
def test_invalid_dense_vectors_fail_without_lexical_fallback(vector):
    class Broken:
        def passage_embed(self, texts):
            return [vector] * len(texts)

        def query_embed(self, query):
            return [[1.0, 0.0]]

    with pytest.raises(DataError) as error:
        retrieve("backtest", DOCS, mode="dense", encoder=Broken())
    assert error.value.code == "embedding_failed"


def test_duplicate_artifact_ids_are_rejected():
    with pytest.raises(DataError) as error:
        retrieve("trial", [DOCS[0], DOCS[0]])
    assert error.value.code == "duplicate_retrieval_document"


def test_persistent_dense_cache_reuses_exact_text_and_rebuilds_corruption(tmp_path):
    class Encoder:
        calls = 0

        def passage_embed(self, texts):
            self.calls += len(texts)
            return [[1.0, 2.0] for _ in texts]

        def query_embed(self, query):
            return [[1.0, 0.0]]

    encoder = Encoder()
    first = retrieve("test", DOCS, mode="dense", encoder=encoder, cache_dir=tmp_path)
    assert encoder.calls == 2
    assert first["embedding_cache_hits"] == 0
    second = retrieve("other query", DOCS, mode="dense", encoder=encoder, cache_dir=tmp_path)
    assert second["embedding_cache_hits"] == 2
    assert encoder.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert list(tmp_path.glob(".embedding-*")) == []
    next(tmp_path.glob("*.json")).write_text("broken json")
    rebuilt = retrieve("test", DOCS, mode="dense", encoder=encoder, cache_dir=tmp_path)
    assert rebuilt["embedding_cache_hits"] == 1
    assert encoder.calls == 3
    revised = [{**DOCS[0], "title": "Changed title"}, DOCS[1]]
    changed = retrieve("test", revised, mode="dense", encoder=encoder, cache_dir=tmp_path)
    assert changed["embedding_cache_hits"] == 1
    assert encoder.calls == 4
    retrieve(
        "test",
        revised,
        mode="dense",
        model_name="different-model",
        encoder=encoder,
        cache_dir=tmp_path,
    )
    assert encoder.calls == 6


def test_cache_dimension_mismatch_is_recomputed(tmp_path):
    class Encoder:
        dimension = 2
        calls = 0

        def passage_embed(self, texts):
            self.calls += len(texts)
            return [[1.0] * self.dimension for _ in texts]

        def query_embed(self, query):
            return [[1.0] * self.dimension]

    encoder = Encoder()
    retrieve("test", DOCS, mode="dense", encoder=encoder, cache_dir=tmp_path)
    encoder.dimension = 3
    result = retrieve("test", DOCS, mode="dense", encoder=encoder, cache_dir=tmp_path)
    assert result["embedding_cache_hits"] == 0
    assert encoder.calls == 4
