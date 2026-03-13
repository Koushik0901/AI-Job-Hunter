from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend import evidence_index


def _sample_assets() -> dict:
    return {
        "evidence_context": {
            "summary": "Built retrieval augmented generation pipelines in Python and FastAPI.",
            "skills": ["python", "fastapi", "qdrant", "langchain"],
        },
        "brag_document_markdown": "Improved ranking quality by 18% on production traffic.",
        "project_cards": [{"title": "Search", "impact": "Cut p95 latency to 180ms"}],
    }


def test_build_evidence_pack_prefers_overlap() -> None:
    pack = evidence_index.build_evidence_pack("Need Python FastAPI and retrieval experience", _sample_assets(), top_k=4)
    assert pack["algorithm"] == "lexical_overlap_v1"
    assert int(pack["total_chunks"]) >= 1
    assert isinstance(pack.get("thresholds"), dict)
    selected = pack["selected_chunks"]
    assert isinstance(selected, list)
    assert len(selected) >= 1
    assert any("python" in str(row.get("text", "")).lower() for row in selected)
    assert any(isinstance(row.get("metadata"), dict) for row in selected)


def test_build_runtime_evidence_pack_lexical_mode(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_RETRIEVAL_MODE", "lexical")
    pack = evidence_index.build_runtime_evidence_pack("python fastapi", _sample_assets(), profile_id="default", top_k=3)
    assert pack["algorithm"] == "lexical_overlap_v1"
    assert len(pack["selected_chunks"]) >= 1


def test_build_runtime_evidence_pack_hybrid_merges_qdrant_and_lexical(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_RETRIEVAL_MODE", "auto")

    def _fake_qdrant(*_args, **_kwargs):
        return {
            "algorithm": "qdrant_vector_v1",
            "total_chunks": 1,
            "selected_chunks": [
                {
                    "chunk_id": "q:1",
                    "source_type": "project_card",
                    "source_key": "Search",
                    "score": 0.91,
                    "overlap_terms": [],
                    "text": "Built a retrieval evaluator with LangChain.",
                }
            ],
        }

    monkeypatch.setattr(evidence_index, "query_qdrant_evidence_pack", _fake_qdrant)
    pack = evidence_index.build_runtime_evidence_pack("retrieval langchain", _sample_assets(), profile_id="default", top_k=5)
    assert pack["algorithm"] == "hybrid_v1"
    assert isinstance(pack.get("sources"), dict)
    assert isinstance(pack.get("thresholds"), dict)
    assert len(pack["selected_chunks"]) >= 1
    assert any("retrieval" in str(row.get("text", "")).lower() for row in pack["selected_chunks"])
