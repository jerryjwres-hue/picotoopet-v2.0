"""Content Radar topic clustering stays deterministic and model-free."""

from __future__ import annotations

from picotoopet_core.autonomous.content_radar import (
    RadarCandidateInput,
    cluster_candidates,
    normalize_candidates,
)


def _candidate(evidence: str, url: str, title: str, excerpt: str):  # type: ignore[no-untyped-def]
    return RadarCandidateInput(
        evidence_id=evidence,
        url=url,
        title=title,
        excerpt=excerpt,
    )


def test_obvious_token_overlap_topics_cluster_and_unrelated_topic_stays_separate() -> None:
    candidates = normalize_candidates(
        [
            _candidate(
                "e1",
                "https://example.com/dog-office",
                "Dog office comedy trend",
                "office dog comedy short video trend",
            ),
            _candidate(
                "e2",
                "https://example.net/office-dog",
                "Office dog comedy format",
                "dog office comedy short clip trend",
            ),
            _candidate(
                "e3",
                "https://example.org/cat-food",
                "Cat nutrition complaint",
                "owners compare wet cat food ingredients",
            ),
        ]
    )

    clusters = cluster_candidates(candidates, similarity_threshold=0.45)

    assert sorted(len(cluster.candidate_ids) for cluster in clusters) == [1, 2]
    dog_cluster = next(cluster for cluster in clusters if len(cluster.candidate_ids) == 2)
    assert dog_cluster.evidence_ids == ["e1", "e2"]
    assert "dog" in dog_cluster.representative_text.casefold()


def test_input_order_does_not_change_cluster_ids_or_members() -> None:
    candidates = normalize_candidates(
        [
            _candidate("a", "https://a.example/a", "AI pet workflow", "pet ai workflow automation"),
            _candidate("b", "https://b.example/b", "Pet AI automation", "ai pet workflow automation"),
            _candidate("c", "https://c.example/c", "Travel camera", "camera packing travel guide"),
        ]
    )

    forward = cluster_candidates(candidates)
    reverse = cluster_candidates(list(reversed(candidates)))

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]


def test_duplicate_evidence_cannot_inflate_cluster_membership() -> None:
    candidates = normalize_candidates(
        [
            _candidate("e1", "https://example.com/x?utm_source=a", "Dog office", "dog office comedy"),
            _candidate("e2", "https://example.com/x", "Dog office", "dog office comedy"),
        ]
    )

    assert len(candidates) == 1
    clusters = cluster_candidates(candidates)

    assert len(clusters) == 1
    assert len(clusters[0].candidate_ids) == 1
    assert clusters[0].evidence_ids == ["e1", "e2"]


def test_similarity_threshold_is_bounded() -> None:
    candidates = normalize_candidates(
        [_candidate("e1", "https://example.com/x", "Dog office", "dog office comedy")]
    )

    for invalid in (-0.01, 1.01):
        try:
            cluster_candidates(candidates, similarity_threshold=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid similarity threshold must be rejected")
