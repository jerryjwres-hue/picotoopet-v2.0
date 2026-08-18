"""Read-only Browser Broker contract migrated from the Maotai OS 4.1 bridge."""

from __future__ import annotations

import pytest

from picotoopet_core.autonomous.browser_broker import validate_browser_capture

_DEFAULT_EXTENSION_ID = "miagfkomnofgeeahbficblhlcgahaldp"


def _packet(**overrides: object) -> dict[str, object]:
    packet: dict[str, object] = {
        "type": "capture_page",
        "extension_id": _DEFAULT_EXTENSION_ID,
        "url": "https://www.amazon.com/dp/B0ABCDEFGHI",
        "page": {
            "title": "Large dog chew toy",
            "product_title": "Large dog chew toy",
            "price": "$29.99",
            "rating": "4.6",
            "review_count": "1,234",
            "visible_signals": [
                {
                    "source_id": "review-1",
                    "text": "Strong toy but the handle is too small for my malamute.",
                    "rating": 4,
                    "author": "public-reviewer",
                }
            ],
        },
    }
    packet.update(overrides)
    return packet


def test_accepts_public_capture_and_returns_bounded_sanitized_evidence() -> None:
    evidence = validate_browser_capture(_packet())

    assert evidence.message_type == "capture_page"
    assert evidence.source_url == "https://www.amazon.com/dp/B0ABCDEFGHI"
    assert evidence.domain == "www.amazon.com"
    assert evidence.platform == "amazon"
    assert evidence.title == "Large dog chew toy"
    assert evidence.observations["rating"] == 4.6
    assert evidence.observations["review_count"] == 1234
    assert len(evidence.public_signals) == 1
    assert evidence.public_signals[0]["text"].startswith("Strong toy")
    assert evidence.evidence_id.startswith("browser-")


def test_same_public_capture_has_stable_evidence_id() -> None:
    first = validate_browser_capture(_packet())
    second = validate_browser_capture(_packet())
    assert first.evidence_id == second.evidence_id


@pytest.mark.parametrize(
    "message_type",
    ["capture_product", "capture_page", "capture_visible_signals", "send_to_current_product", "capture_batch_v4"],
)
def test_accepts_legacy_capture_message_family(message_type: str) -> None:
    evidence = validate_browser_capture(_packet(type=message_type))
    assert evidence.message_type == message_type


def test_ping_and_completion_packets_are_not_evidence_documents() -> None:
    with pytest.raises(ValueError, match="evidence-bearing"):
        validate_browser_capture({"type": "ping", "extension_id": _DEFAULT_EXTENSION_ID})
    with pytest.raises(ValueError, match="evidence-bearing"):
        validate_browser_capture(
            {
                "type": "capture_complete_v4",
                "extension_id": _DEFAULT_EXTENSION_ID,
                "protocol_version": 4,
                "capture_run_id": "run-1",
            }
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/private.txt",
        "http://localhost:8080/page",
        "http://127.0.0.1/page",
        "http://10.0.0.8/page",
        "https://user:password@example.com/page",
    ],
)
def test_rejects_non_public_or_credential_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_browser_capture(_packet(url=url))


def test_rejects_wrong_extension_when_allowlist_is_supplied() -> None:
    with pytest.raises(ValueError, match="extension"):
        validate_browser_capture(_packet(extension_id="unexpected"), allowed_extension_id=_DEFAULT_EXTENSION_ID)


@pytest.mark.parametrize(
    "secret_key",
    [
        "cookie",
        "authorization",
        "access_token",
        "refresh-token",
        "password",
        "credit_card",
        "localStorage",
        "sessionStorage",
        "session_token",
    ],
)
def test_rejects_forbidden_secret_or_session_keys_recursively(secret_key: str) -> None:
    packet = _packet()
    packet["page"] = {"title": "safe", "nested": {secret_key: "must-never-enter-core"}}
    with pytest.raises(ValueError, match="secret/session"):
        validate_browser_capture(packet)


def test_rejects_payloads_larger_than_480_kib() -> None:
    packet = _packet()
    packet["page"] = {"title": "x", "visible_signals": [{"text": "x" * (481 * 1024)}]}
    with pytest.raises(ValueError, match="size"):
        validate_browser_capture(packet)


def test_visible_signals_are_bounded_without_inventing_missing_values() -> None:
    packet = _packet()
    packet["page"] = {
        "title": "Public page",
        "visible_signals": [
            {"source_id": f"s-{index}", "text": ("visible text " * 1000)}
            for index in range(80)
        ],
    }
    evidence = validate_browser_capture(packet)

    assert len(evidence.public_signals) == 50
    assert all(len(item["text"]) <= 5000 for item in evidence.public_signals)
    assert "rating" not in evidence.public_signals[0]


def test_unknown_message_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="message type"):
        validate_browser_capture(_packet(type="execute_javascript"))
