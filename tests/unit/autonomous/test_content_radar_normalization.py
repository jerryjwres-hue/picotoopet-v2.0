"""Deterministic Content Radar normalization must remove tracking noise without inventing data."""

from __future__ import annotations

import pytest

from picotoopet_core.autonomous.content_radar import (
    RadarCandidateInput,
    normalize_candidates,
)


def test_tracking_query_and_fragment_normalize_to_one_candidate() -> None:
    candidates = normalize_candidates(
        [
            RadarCandidateInput(
                evidence_id="ev-2",
                url="https://Example.com/pet/video?utm_source=x&id=42#comments",
                title="Dog office trend",
                excerpt="A dog goes to work in a short comedy format.",
                platform="web",
            ),
            RadarCandidateInput(
                evidence_id="ev-1",
                url="https://example.com/pet/video?id=42&utm_medium=y",
                title="Dog office trend",
                excerpt="A dog goes to work in a short comedy format.",
                platform="web",
            ),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.canonical_url == "https://example.com/pet/video?id=42"
    assert candidate.domain == "example.com"
    assert candidate.evidence_ids == ["ev-1", "ev-2"]
    assert candidate.candidate_id.startswith("radar-")


def test_exact_text_duplicate_across_urls_collapses_without_losing_evidence() -> None:
    candidates = normalize_candidates(
        [
            RadarCandidateInput(
                evidence_id="source-a",
                url="https://example.com/a",
                title="Same story",
                excerpt="Pet owners repeat the same complaint about shedding.",
                platform="reviews",
            ),
            RadarCandidateInput(
                evidence_id="source-b",
                url="https://mirror.example.net/b",
                title="Same story",
                excerpt="  Pet owners repeat the SAME complaint about shedding.  ",
                platform="reviews",
            ),
        ]
    )

    assert len(candidates) == 1
    assert candidates[0].evidence_ids == ["source-a", "source-b"]


def test_input_order_does_not_change_output_order_or_ids() -> None:
    inputs = [
        RadarCandidateInput(
            evidence_id="z",
            url="https://b.example.com/two",
            title="Second",
            excerpt="Distinct topic beta",
        ),
        RadarCandidateInput(
            evidence_id="a",
            url="https://a.example.com/one",
            title="First",
            excerpt="Distinct topic alpha",
        ),
    ]

    forward = normalize_candidates(inputs)
    reverse = normalize_candidates(list(reversed(inputs)))

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert [item.canonical_url for item in forward] == [
        "https://a.example.com/one",
        "https://b.example.com/two",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "https://user:password@example.com/private",
    ],
)
def test_unsafe_or_non_public_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_candidates(
            [
                RadarCandidateInput(
                    evidence_id="unsafe",
                    url=url,
                    title="Unsafe",
                    excerpt="Unsafe candidate",
                )
            ]
        )


def test_candidate_contract_rejects_empty_evidence_and_oversized_text() -> None:
    with pytest.raises(ValueError):
        RadarCandidateInput(
            evidence_id="",
            url="https://example.com/a",
            title="x",
            excerpt="body",
        )
    with pytest.raises(ValueError):
        RadarCandidateInput(
            evidence_id="ev",
            url="https://example.com/a",
            title="x" * 501,
            excerpt="body",
        )
