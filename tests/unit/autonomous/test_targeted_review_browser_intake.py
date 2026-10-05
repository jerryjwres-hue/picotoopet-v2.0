"""Regression contracts for Maotai-style targeted review batches entering Mac Core."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.autonomous.connected_evidence import (
    BrowserCaptureIntake,
    ConnectedEvidenceRepository,
)
from picotoopet_core.db.database import Database


_EXTENSION_ID = "miagfkomnofgeeahbficblhlcgahaldp"
_AMAZON_URL = "https://www.amazon.com/dp/B0ABCDEFGHI"


def _core(tmp_path: Path) -> tuple[Database, ConnectedEvidenceRepository]:
    database = Database(tmp_path / "runtime" / "database" / "core.db")
    database.open()
    database.apply_migrations()
    return database, ConnectedEvidenceRepository(database)


def _review_batch() -> dict[str, object]:
    """Model one bounded Browser Bridge batch from the old per-star review collector."""

    return {
        "type": "capture_batch_v4",
        "extension_id": _EXTENSION_ID,
        "url": _AMAZON_URL,
        "page": {
            "visible_signals": [
                {
                    "source_id": f"review-{rating}",
                    "stable_key": f"amazon:B0ABCDEFGHI:review-{rating}",
                    "text": f"Public review text for {rating} stars",
                    "rating": rating,
                    "date": "2026-08-20",
                    "author": f"reviewer-{rating}",
                    "source_url": f"{_AMAZON_URL}#review-{rating}",
                    "verified": True,
                    "signal_kind": "review",
                }
                for rating in (5, 4, 3, 2, 1)
            ]
        },
    }


def test_targeted_review_batch_preserves_star_rating_and_review_metadata(tmp_path: Path) -> None:
    """Mac Core must preserve the fields needed for 5/4/3/2/1-star targeted analysis."""

    database, repository = _core(tmp_path)
    intake = BrowserCaptureIntake(repository, allowed_extension_id=_EXTENSION_ID)
    try:
        record = intake.ingest(_review_batch(), idempotency_key="amazon-review-batch-0001")

        assert record.platform == "amazon"
        assert record.capture_type == "capture_batch_v4"
        assert record.evidence_count == 5

        evidence = repository.list_evidence(product_key=record.product_key, limit=20)
        assert len(evidence) == 5
        assert {item.numeric_value for item in evidence} == {1.0, 2.0, 3.0, 4.0, 5.0}
        assert all(item.evidence_type == "consumer_signal" for item in evidence)
        assert all(item.value.get("signal_kind") == "review" for item in evidence)
        assert all(item.value.get("verified") is True for item in evidence)
        assert {item.source_entity_id for item in evidence} == {
            "review-1",
            "review-2",
            "review-3",
            "review-4",
            "review-5",
        }
    finally:
        database.close()


def test_targeted_review_recollection_dedupes_same_public_reviews(tmp_path: Path) -> None:
    """A later scan may revisit thousands of reviews; unchanged reviews must not be saved twice."""

    database, repository = _core(tmp_path)
    intake = BrowserCaptureIntake(repository, allowed_extension_id=_EXTENSION_ID)
    try:
        first = intake.ingest(_review_batch(), idempotency_key="amazon-review-scan-0001")
        second = intake.ingest(_review_batch(), idempotency_key="amazon-review-scan-0002")

        assert first.evidence_count == 5
        assert second.evidence_count == 0
        assert repository.count_evidence() == 5
    finally:
        database.close()
