"""Inspectable chunk retrieval: BM25 lexical or explicitly configured dense search.

Indexes are derived from immutable artifact documents. Scores are relevance
measures, not calibrated probabilities. Dense mode never silently becomes lexical.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np

from .errors import DataError


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _chunks(documents: list[dict], chunk_chars: int = 1800, overlap: int = 200) -> list[dict]:
    chunks = []
    seen = set()
    for doc in documents:
        if not isinstance(doc.get("id"), str) or not doc["id"]:
            raise DataError(
                "invalid_retrieval_document", "each library document needs an artifact ID"
            )
        if doc["id"] in seen:
            raise DataError("duplicate_retrieval_document", "artifact IDs must be unique")
        seen.add(doc["id"])
        content = doc.get("content", "")
        text = (
            content
            if isinstance(content, str)
            else json.dumps(content, sort_keys=True, ensure_ascii=False)
        )
        if len(text) > 2_000_000:
            raise DataError("retrieval_document_too_large", "document exceeds the indexing limit")
        for start in range(0, len(text), chunk_chars - overlap):
            snippet = text[start : start + chunk_chars]
            if not snippet.strip():
                continue
            if len(chunks) >= 10000:
                raise DataError(
                    "retrieval_corpus_too_large", "in-process search supports at most 10000 chunks"
                )
            chunks.append(
                {
                    "artifact_id": doc["id"],
                    "title": str(doc.get("title", "")),
                    "artifact_sha256": doc.get("sha256"),
                    "start_char": start,
                    "end_char": start + len(snippet),
                    "text": snippet,
                    "chunk_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
                }
            )
            if start + chunk_chars >= len(text):
                break
    return chunks


@lru_cache(maxsize=2)
def _encoder(model_name: str):
    # Supported public embedding models do not need account credentials. Avoid
    # attaching ambient HuggingFace login tokens to automatic model downloads.
    # Deployment also sets this before imports; an explicit operator value wins.
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise DataError(
            "dense_retrieval_unavailable", "install the retrieval extra to enable dense search"
        ) from exc
    try:
        return TextEmbedding(model_name=model_name)
    except Exception as exc:
        raise DataError(
            "embedding_model_unavailable", "configured embedding model could not be loaded"
        ) from exc


def _embedding_key(model_name: str, text: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "schema": 1,
                "model": model_name,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _cached_vector(
    cache_dir: Path, model_name: str, text: str, dimension: int
) -> list[float] | None:
    key = _embedding_key(model_name, text)
    path = cache_dir / f"{key}.json"
    try:
        # Cache data is untrusted/rebuildable, not an authoritative research artifact.
        if path.stat().st_size > 500_000:
            return None
        data = json.loads(path.read_text())
        values = np.asarray(data["vector"], dtype=float)
        if (
            data.get("key") != key
            or data.get("model") != model_name
            or values.shape != (dimension,)
            or not np.isfinite(values).all()
            or np.linalg.norm(values) == 0
        ):
            return None
        return values.tolist()
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save_vector(cache_dir: Path, model_name: str, text: str, vector: list[float]) -> None:
    key = _embedding_key(model_name, text)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=cache_dir, prefix=".embedding-", delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump({"key": key, "model": model_name, "vector": vector}, output, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, cache_dir / f"{key}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def retrieve(
    query: str,
    documents: list[dict],
    *,
    mode: Literal["lexical", "dense"] = "lexical",
    model_name: str = "BAAI/bge-small-en-v1.5",
    limit: int = 5,
    encoder=None,
    cache_dir: str | Path | None = None,
) -> dict:
    """Return attributable passages. Embeddings are local and optionally cached by model.

    `encoder` is injectable for tests; production explicitly instantiates fastembed.
    Persistent document vectors key the exact model name and full encoded text
    hash (title plus chunk). Writes are atomic; corrupt/dimension-mismatched
    cache entries are rebuilt. The search index is never authoritative.
    """
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 4000
        or type(limit) is not int
        or not 1 <= limit <= 30
    ):
        raise DataError(
            "invalid_retrieval_query", "provide a bounded query and limit between 1 and 30"
        )
    if mode not in {"lexical", "dense"}:
        raise DataError("invalid_retrieval_mode", "retrieval mode must be lexical or dense")
    if len(documents) > 1000:
        raise DataError(
            "retrieval_corpus_too_large", "in-process search supports at most 1000 artifacts"
        )
    chunks = _chunks(documents)
    if len(chunks) > 10000:
        raise DataError(
            "retrieval_corpus_too_large", "in-process search supports at most 10000 chunks"
        )
    if not chunks:
        return {
            "items": [],
            "mode": mode,
            "model": model_name if mode == "dense" else "BM25",
            "corpus_artifacts": len(documents),
            "corpus_chunks": 0,
        }
    texts = [f"{item['title']}\n{item['text']}" for item in chunks]
    cache_hits = 0
    if mode == "dense":
        encoder = encoder or _encoder(model_name)
        try:
            # Query/document methods preserve model-specific retrieval prefixes.
            query_vectors = np.asarray(list(encoder.query_embed(query)), dtype=float)
            if (
                query_vectors.ndim != 2
                or query_vectors.shape[0] != 1
                or not 1 <= query_vectors.shape[1] <= 4096
            ):
                raise ValueError("unexpected query embedding shape")
            dimension = query_vectors.shape[1]
            cache_path = Path(cache_dir) if cache_dir is not None else None
            rows = [
                _cached_vector(cache_path, model_name, text, dimension) if cache_path else None
                for text in texts
            ]
            missing = [index for index, row in enumerate(rows) if row is None]
            cache_hits = len(rows) - len(missing)
            if missing:
                encoded = list(encoder.passage_embed([texts[index] for index in missing]))
                if len(encoded) != len(missing):
                    raise ValueError("unexpected document embedding count")
                for index, vector in zip(missing, encoded, strict=True):
                    value = np.asarray(vector, dtype=float)
                    if (
                        value.shape != (dimension,)
                        or not np.isfinite(value).all()
                        or np.linalg.norm(value) == 0
                    ):
                        raise ValueError("invalid document embedding")
                    rows[index] = value.tolist()
                    if cache_path:
                        _save_vector(cache_path, model_name, texts[index], rows[index])
            vectors = np.asarray(rows, dtype=float)
            norms = np.linalg.norm(vectors, axis=1)
            query_norm = np.linalg.norm(query_vectors[0])
            if (
                not np.isfinite(vectors).all()
                or not np.isfinite(query_vectors).all()
                or np.any(norms == 0)
                or query_norm == 0
            ):
                raise ValueError("invalid embedding values")
            scores = (vectors @ query_vectors[0] / (norms * query_norm)).tolist()
        except Exception as exc:
            if isinstance(exc, DataError):
                raise
            raise DataError(
                "embedding_failed", "dense retrieval could not produce valid embeddings"
            ) from exc
    else:
        tokenized = [_tokens(text) for text in texts]
        counts = [Counter(tokens) for tokens in tokenized]
        lengths = [len(tokens) for tokens in tokenized]
        average = sum(lengths) / len(lengths) or 1.0
        document_frequency = Counter(token for tokens in tokenized for token in set(tokens))
        wanted = set(_tokens(query))
        scores = []
        for count, length in zip(counts, lengths, strict=True):
            score = 0.0
            for token in wanted:
                frequency = count[token]
                if frequency:
                    idf = math.log(
                        1
                        + (len(chunks) - document_frequency[token] + 0.5)
                        / (document_frequency[token] + 0.5)
                    )
                    score += (
                        idf
                        * (frequency * 2.5)
                        / (frequency + 1.5 * (0.25 + 0.75 * length / average))
                    )
            scores.append(score)
    ranked = sorted(
        zip(chunks, scores, strict=True),
        key=lambda pair: (-pair[1], pair[0]["artifact_id"], pair[0]["start_char"]),
    )
    items = [
        {**chunk, "score": float(score)} for chunk, score in ranked if mode == "dense" or score > 0
    ][:limit]
    return {
        "items": items,
        "mode": mode,
        "model": model_name if mode == "dense" else "BM25",
        "corpus_artifacts": len(documents),
        "corpus_chunks": len(chunks),
        "score_semantics": "cosine similarity" if mode == "dense" else "BM25 relevance",
        "embedding_cache_hits": cache_hits if mode == "dense" else None,
    }
