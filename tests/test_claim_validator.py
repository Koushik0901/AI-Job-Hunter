from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.claim_validator import build_claim_policy, validate_claim_text


def _policy() -> dict:
    return build_claim_policy(
        current_latex="Built a retrieval assistant with LangChain and Milvus.",
        evidence_context={"work": [{"summary": "Partnered with MITACS researchers on evaluation design."}]},
        evidence_pack={
            "selected_chunks": [
                {"chunk_id": "ctx:1", "text": "Partnered with MITACS researchers on evaluation design."},
                {"chunk_id": "ctx:2", "text": "Built a retrieval assistant with LangChain and Milvus."},
            ]
        },
        brag_document_markdown="",
        project_cards=[],
        do_not_claim=[],
    )


def test_claim_validator_blocks_unsupported_strict_phrase() -> None:
    allowed, reason = validate_claim_text(
        "I am a Canadian permanent resident and worked with geoscientists.",
        _policy(),
        old_text="I built a retrieval assistant.",
        supported_by=["ctx:2"],
    )
    assert allowed is False
    assert reason in {
        "unsupported_strict_phrase:permanent resident",
        "unsupported_strict_phrase:geoscientists",
        "unsupported_strict_phrase:geoscientist",
    }


def test_claim_validator_allows_strict_phrase_when_supported() -> None:
    allowed, reason = validate_claim_text(
        "I partnered with MITACS researchers on evaluation design.",
        _policy(),
        old_text="I built a retrieval assistant.",
        supported_by=["ctx:1"],
    )
    assert allowed is True
    assert reason is None
