from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+.#/-]{1,}")


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    source_type: str
    source_key: str
    text: str
    metadata: dict[str, Any]


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(value or "")]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key}: {_stringify(item)}" for key, item in value.items())
    return str(value)


def _flatten_dict_items(prefix: str, value: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten_dict_items(next_prefix, item))
        return out
    if isinstance(value, list):
        for index, item in enumerate(value):
            next_prefix = f"{prefix}[{index}]"
            out.extend(_flatten_dict_items(next_prefix, item))
        return out
    text = _stringify(value).strip()
    if text:
        out.append((prefix or "value", text))
    return out


def _chunk_fingerprint(text: str) -> str:
    tokens = _tokenize(text)
    compact = " ".join(tokens[:40])
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def build_evidence_chunks(evidence_assets: dict[str, Any]) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    evidence_context = evidence_assets.get("evidence_context")
    if isinstance(evidence_context, dict):
        for key, text in _flatten_dict_items("evidence", evidence_context):
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"ctx:{len(chunks)}",
                    source_type="evidence_context",
                    source_key=key,
                    text=text,
                    metadata={"asset_type": "evidence_context", "tags": [key]},
                )
            )
    brag_doc = str(evidence_assets.get("brag_document_markdown") or "").strip()
    if brag_doc:
        for index, paragraph in enumerate(re.split(r"\n\s*\n+", brag_doc), start=1):
            text = paragraph.strip()
            if not text:
                continue
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"brag:{index}",
                    source_type="brag_document",
                    source_key=f"paragraph_{index}",
                    text=text,
                    metadata={"asset_type": "brag_document", "tags": [f"paragraph_{index}"]},
                )
            )
    project_cards = evidence_assets.get("project_cards")
    if isinstance(project_cards, list):
        for index, card in enumerate(project_cards, start=1):
            if not isinstance(card, dict):
                continue
            text = _stringify(card).strip()
            if not text:
                continue
            title = str(card.get("title") or card.get("name") or f"project_{index}")
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"project:{index}",
                    source_type="project_card",
                    source_key=title,
                    text=text,
                    metadata={
                        "asset_type": "project_card",
                        "project": title,
                        "role": str(card.get("role") or ""),
                        "time": str(card.get("time") or card.get("period") or ""),
                        "tags": [str(tag) for tag in (card.get("tags") or []) if str(tag).strip()],
                    },
                )
            )
    deduped: list[EvidenceChunk] = []
    seen_fingerprints: set[str] = set()
    for item in chunks:
        fingerprint = _chunk_fingerprint(item.text)
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        deduped.append(item)
    return deduped


def build_evidence_pack(job_description: str, evidence_assets: dict[str, Any], top_k: int = 8) -> dict[str, Any]:
    min_overlap = max(0, int(os.getenv("EVIDENCE_MIN_LEXICAL_OVERLAP", "1")))
    capped_k = max(1, min(int(top_k), int(os.getenv("EVIDENCE_MAX_TOP_K", "12"))))
    chunks = build_evidence_chunks(evidence_assets)
    jd_tokens = set(_tokenize(job_description))
    ranked: list[dict[str, Any]] = []
    for item in chunks:
        tokens = set(_tokenize(item.text))
        overlap = jd_tokens.intersection(tokens)
        score = len(overlap)
        ranked.append(
            {
                "chunk_id": item.chunk_id,
                "source_type": item.source_type,
                "source_key": item.source_key,
                "score": score,
                "overlap_terms": sorted(overlap)[:20],
                "text": item.text,
                "metadata": dict(item.metadata or {}),
            }
        )
    ranked.sort(key=lambda row: (int(row["score"]), len(str(row["text"]))), reverse=True)
    top = [row for row in ranked if int(row["score"]) >= min_overlap][:capped_k]
    if not top:
        top = ranked[: max(1, min(capped_k, len(ranked)))]
    return {
        "algorithm": "lexical_overlap_v1",
        "total_chunks": len(chunks),
        "selected_chunks": top,
        "thresholds": {"min_lexical_overlap": min_overlap, "top_k": capped_k},
    }


def _qdrant_client() -> Any:
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    if not qdrant_url:
        return None
    try:
        from qdrant_client import QdrantClient
    except Exception:
        return None
    return QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY", "").strip() or None, timeout=20)


def query_qdrant_evidence_pack(job_description: str, *, profile_id: str = "default", top_k: int = 8) -> dict[str, Any]:
    client = _qdrant_client()
    collection = os.getenv("QDRANT_EVIDENCE_COLLECTION", "candidate_evidence_chunks").strip() or "candidate_evidence_chunks"
    if client is None:
        return {
            "algorithm": "qdrant_disabled",
            "total_chunks": 0,
            "selected_chunks": [],
        }
    try:
        min_vector_score = float(os.getenv("EVIDENCE_MIN_VECTOR_SCORE", "0.15"))
        vector = _embed_texts_openrouter([job_description])[0]
        query_filter = None
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            query_filter = Filter(
                must=[
                    FieldCondition(key="profile_id", match=MatchValue(value=profile_id)),
                ]
            )
        except Exception:
            query_filter = None
        results = client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=query_filter,
            limit=max(1, int(top_k)),
            with_payload=True,
        )
        points = getattr(results, "points", None) or []
        selected: list[dict[str, Any]] = []
        for row in points:
            score = float(getattr(row, "score", 0.0) or 0.0)
            if score < min_vector_score:
                continue
            payload = getattr(row, "payload", {}) or {}
            selected.append(
                {
                    "chunk_id": str(payload.get("chunk_id") or getattr(row, "id", "")),
                    "source_type": str(payload.get("source_type") or "qdrant"),
                    "source_key": str(payload.get("source_key") or ""),
                    "score": score,
                    "overlap_terms": [],
                    "text": str(payload.get("text") or ""),
                    "metadata": dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {},
                }
            )
        return {
            "algorithm": "qdrant_vector_v1",
            "total_chunks": len(selected),
            "selected_chunks": selected,
            "thresholds": {"min_vector_score": min_vector_score},
        }
    except Exception:
        return {
            "algorithm": "qdrant_error",
            "total_chunks": 0,
            "selected_chunks": [],
        }


def build_runtime_evidence_pack(
    job_description: str,
    evidence_assets: dict[str, Any],
    *,
    profile_id: str = "default",
    top_k: int = 8,
) -> dict[str, Any]:
    mode = (os.getenv("EVIDENCE_RETRIEVAL_MODE", "auto").strip().lower() or "auto")
    capped_k = max(1, min(int(top_k), int(os.getenv("EVIDENCE_MAX_TOP_K", "12"))))
    lexical = build_evidence_pack(job_description, evidence_assets, top_k=capped_k)
    if mode == "lexical":
        return lexical
    qdrant = query_qdrant_evidence_pack(job_description, profile_id=profile_id, top_k=capped_k)
    if mode == "qdrant":
        return qdrant if qdrant.get("selected_chunks") else lexical

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_list in (qdrant.get("selected_chunks") or [], lexical.get("selected_chunks") or []):
        if not isinstance(source_list, list):
            continue
        for source in source_list:
            if not isinstance(source, dict):
                continue
            key = f"{source.get('source_type')}::{source.get('source_key')}::{_chunk_fingerprint(str(source.get('text') or ''))}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
            if len(merged) >= capped_k:
                break
        if len(merged) >= capped_k:
            break
    return {
        "algorithm": "hybrid_v1",
        "total_chunks": int(lexical.get("total_chunks") or 0),
        "selected_chunks": merged,
        "sources": {
            "lexical": lexical.get("algorithm"),
            "qdrant": qdrant.get("algorithm"),
        },
        "thresholds": {
            "min_lexical_overlap": (lexical.get("thresholds") or {}).get("min_lexical_overlap"),
            "min_vector_score": (qdrant.get("thresholds") or {}).get("min_vector_score"),
            "top_k": capped_k,
        },
    }


def _asset_version_id(evidence_assets: dict[str, Any]) -> str:
    payload = json.dumps(evidence_assets, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _embed_cache_path() -> Path:
    configured = os.getenv("EVIDENCE_EMBED_CACHE_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path("artifacts_workspace") / "evidence_embedding_cache.json"


def _load_embed_cache() -> dict[str, list[float]]:
    path = _embed_cache_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): [float(v) for v in values] for k, values in raw.items() if isinstance(values, list)}
    except Exception:
        return {}
    return {}


def _save_embed_cache(cache: dict[str, list[float]]) -> None:
    path = _embed_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _embed_with_cache(*, profile_id: str, asset_version_id: str, texts: list[str]) -> list[list[float]]:
    model = os.getenv("EVIDENCE_EMBED_MODEL", "openai/text-embedding-3-small").strip() or "openai/text-embedding-3-small"
    cache = _load_embed_cache()
    vectors: list[list[float]] = []
    misses: list[tuple[int, str]] = []
    keys: list[str] = []
    for index, text in enumerate(texts):
        chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = f"{profile_id}|{asset_version_id}|{chunk_hash}|{model}"
        keys.append(key)
        if key in cache:
            vectors.append(cache[key])
        else:
            vectors.append([])
            misses.append((index, text))
    if misses:
        miss_vectors = _embed_texts_openrouter([text for _, text in misses])
        for (index, _text), vector in zip(misses, miss_vectors):
            vectors[index] = vector
            cache[keys[index]] = vector
        _save_embed_cache(cache)
    return vectors


def _embed_texts_openrouter(texts: list[str]) -> list[list[float]]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("EVIDENCE_EMBED_MODEL", "openai/text-embedding-3-small").strip() or "openai/text-embedding-3-small"
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing for embeddings")
    response = requests.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": texts},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("Invalid embeddings response")
    vectors: list[list[float]] = []
    for row in data:
        emb = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(emb, list):
            raise RuntimeError("Invalid embedding vector")
        vectors.append([float(v) for v in emb])
    return vectors


def reindex_evidence_assets(profile_id: str, evidence_assets: dict[str, Any]) -> dict[str, Any]:
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    collection = os.getenv("QDRANT_EVIDENCE_COLLECTION", "candidate_evidence_chunks").strip() or "candidate_evidence_chunks"
    chunks = build_evidence_chunks(evidence_assets)
    if not qdrant_url:
        return {
            "enabled": False,
            "backend": "disabled",
            "status": "skipped",
            "indexed_count": len(chunks),
            "message": "QDRANT_URL not configured; lexical retrieval remains active.",
            "updated_at": time.time(),
        }
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except Exception as error:
        return {
            "enabled": False,
            "backend": "qdrant",
            "status": "failed",
            "indexed_count": 0,
            "message": f"qdrant-client unavailable: {error}",
            "updated_at": time.time(),
        }

    texts = [item.text for item in chunks]
    asset_version_id = _asset_version_id(evidence_assets)
    if not texts:
        return {
            "enabled": True,
            "backend": "qdrant",
            "status": "ok",
            "indexed_count": 0,
            "message": "No evidence chunks to index.",
            "updated_at": time.time(),
            "asset_version_id": asset_version_id,
        }
    try:
        vectors = _embed_with_cache(profile_id=profile_id, asset_version_id=asset_version_id, texts=texts)
        client = QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY", "").strip() or None, timeout=20)
        vector_size = len(vectors[0])
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        points: list[PointStruct] = []
        for index, item in enumerate(chunks):
            payload = {
                "profile_id": profile_id,
                "source_type": item.source_type,
                "source_key": item.source_key,
                "text": item.text,
                "asset_version_id": asset_version_id,
                "metadata": dict(item.metadata or {}),
            }
            points.append(
                PointStruct(
                    id=index + 1,
                    vector=vectors[index],
                    payload=payload,
                )
            )
        client.upsert(collection_name=collection, points=points)
        return {
            "enabled": True,
            "backend": "qdrant",
            "status": "ok",
            "indexed_count": len(points),
            "message": "Evidence vectors indexed.",
            "updated_at": time.time(),
            "collection": collection,
            "asset_version_id": asset_version_id,
        }
    except Exception as error:
        return {
            "enabled": True,
            "backend": "qdrant",
            "status": "failed",
            "indexed_count": 0,
            "message": str(error),
            "updated_at": time.time(),
            "collection": collection,
            "asset_version_id": asset_version_id,
        }


def evidence_pack_to_json(pack: dict[str, Any]) -> str:
    return json.dumps(pack, ensure_ascii=False)
