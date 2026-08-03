"""Slice D 规范化诊断 JSON 对象存储回归。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from picotoopet_core.results.store import ResultStore, ResultTooLargeError


def test_put_json_is_canonical_and_content_addressed(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)

    first = store.put_json(
        {"b": 2, "a": 1},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )
    manifest_before = first.manifest_path.read_bytes()
    second = store.put_json(
        {"a": 1, "b": 2},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )

    expected = b'{"a":1,"b":2}'
    assert first.object_hash == hashlib.sha256(expected).hexdigest()
    assert second.object_hash == first.object_hash
    assert first.object_path.read_bytes() == expected
    assert second.manifest_path.read_bytes() == manifest_before
    assert store.read_json(first.object_hash, max_bytes=64 * 1024) == {"a": 1, "b": 2}


def test_put_json_repairs_corrupted_existing_object_atomically(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    document = {"schema_version": "1.0", "checks": ["core"]}
    first = store.put_json(
        document,
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )
    first.object_path.write_bytes(b"corrupted-existing-object")

    repaired = store.put_json(
        document,
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )

    assert repaired.object_hash == first.object_hash
    assert store.verify(repaired.object_hash) is True
    assert store.read_json(repaired.object_hash, max_bytes=64 * 1024) == document
    assert list(repaired.object_path.parent.glob(".partial-*")) == []


def test_put_json_rejects_payload_over_limit_without_partial_object(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    document = {"value": "x" * 1024}

    with pytest.raises(ResultTooLargeError):
        store.put_json(
            document,
            result_type="system.diagnostic_snapshot",
            max_bytes=32,
        )

    assert list(store.objects_dir.rglob("*")) == []


def test_read_json_rejects_tampered_object(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    stored = store.put_json(
        {"schema_version": "1.0"},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )
    stored.object_path.write_text(json.dumps({"tampered": True}), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        store.read_json(stored.object_hash, max_bytes=64 * 1024)


def test_read_json_rejects_invalid_json(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    raw = b"not-json"
    object_hash = hashlib.sha256(raw).hexdigest()
    object_path = store._object_path(object_hash)  # noqa: SLF001 - 固定对象布局回归。
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(raw)

    with pytest.raises(ValueError, match="JSON"):
        store.read_json(object_hash, max_bytes=64 * 1024)
