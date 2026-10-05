"""Reliability diagnostics may observe Ollama, but must never mutate model state."""

from __future__ import annotations

import httpx

from picotoopet_core.ollama.client import OllamaClient


def _client(responder):  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(responder)
    raw       = httpx.Client(base_url="http://127.0.0.1:11434", transport=transport)
    return OllamaClient(client=raw), raw


def test_version_observation_is_read_only_and_bounded() -> None:
    calls: list[tuple[str, str]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"version": "0.13.4"})

    client, raw = _client(responder)
    try:
        observation = client.version_info()
    finally:
        raw.close()

    assert observation.version == "0.13.4"
    assert calls == [("GET", "/api/version")]


def test_process_snapshot_exposes_only_safe_runtime_fields() -> None:
    calls: list[tuple[str, str]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "gpt-oss:20b",
                        "model": "gpt-oss:20b",
                        "size": 13_500_000_000,
                        "size_vram": 12_800_000_000,
                        "expires_at": "2026-08-20T06:00:00Z",
                        "digest": "secret-ish-internal-digest-must-not-leak",
                        "details": {"parent_model": "/private/model/path"},
                    }
                ]
            },
        )

    client, raw = _client(responder)
    try:
        snapshot = client.process_snapshot()
    finally:
        raw.close()

    assert calls == [("GET", "/api/ps")]
    assert snapshot.loaded_model_count == 1
    assert len(snapshot.models) == 1
    model = snapshot.models[0]
    assert model.name == "gpt-oss:20b"
    assert model.size_bytes == 13_500_000_000
    assert model.vram_bytes == 12_800_000_000
    assert model.expires_at is not None
    serialized = snapshot.model_dump_json()
    assert "digest" not in serialized
    assert "/private/model/path" not in serialized


def test_process_snapshot_bounds_model_count_and_rejects_mutating_fallbacks() -> None:
    calls: list[tuple[str, str]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": f"model-{index}",
                        "size": index + 1,
                        "size_vram": index + 2,
                    }
                    for index in range(100)
                ]
            },
        )

    client, raw = _client(responder)
    try:
        snapshot = client.process_snapshot()
    finally:
        raw.close()

    assert snapshot.loaded_model_count == 100
    assert len(snapshot.models) == 32
    assert snapshot.truncated is True
    assert calls == [("GET", "/api/ps")]
    assert all(method == "GET" for method, _path in calls)
