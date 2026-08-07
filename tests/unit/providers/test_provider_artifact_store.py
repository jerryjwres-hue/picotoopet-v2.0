from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _api():
    from picotoopet_core.providers.artifact_store import (
        ProviderArtifactError,
        ProviderReturnArtifactStore,
    )
    from picotoopet_core.providers.change_set import ProviderChangeInput

    return ProviderArtifactError, ProviderReturnArtifactStore, ProviderChangeInput


def test_artifact_store_writes_canonical_change_set_payload_diff_and_manifest(
    tmp_path: Path,
) -> None:
    _, Store, Change = _api()
    store = Store(tmp_path / "provider-returns")
    result = store.write(
        return_id="return-001",
        base_commit="a" * 40,
        changes=[
            Change(operation="add", path="docs/new.txt", result_text="hello\n"),
            Change(
                operation="modify",
                path="docs/existing.txt",
                base_sha256="b" * 64,
                result_text="updated\n",
            ),
            Change(
                operation="delete",
                path="docs/old.txt",
                base_sha256="c" * 64,
            ),
        ],
        review_diff="--- a/docs/new.txt\n+++ b/docs/new.txt\n+hello\n",
    )

    assert result.return_id == "return-001"
    assert result.changed_file_count == 3
    assert result.payload_bytes == len("hello\n".encode()) + len("updated\n".encode())
    assert len(result.change_set_digest) == 64
    assert len(result.review_diff_digest) == 64

    artifact_dir = tmp_path / "provider-returns" / "return-001"
    assert (artifact_dir / "change-set.json").is_file()
    assert (artifact_dir / "review.diff").is_file()
    assert (artifact_dir / "payload" / "000.txt").read_text() == "hello\n"
    assert (artifact_dir / "payload" / "001.txt").read_text() == "updated\n"
    assert (artifact_dir / "manifest.sha256").is_file()
    assert not list((tmp_path / "provider-returns").glob(".return-001.tmp-*"))

    change_set = json.loads((artifact_dir / "change-set.json").read_text())
    assert change_set[0]["operation"] == "add"
    assert change_set[0]["path"] == "docs/new.txt"
    assert change_set[0]["base_sha256"] is None
    assert change_set[0]["result_sha256"] == hashlib.sha256(b"hello\n").hexdigest()
    assert change_set[2]["operation"] == "delete"
    assert change_set[2]["payload_name"] is None


def test_artifact_store_reload_reverifies_every_digest_and_rejects_tamper(tmp_path: Path) -> None:
    ArtifactError, Store, Change = _api()
    root = tmp_path / "provider-returns"
    store = Store(root)
    written = store.write(
        return_id="return-002",
        base_commit="d" * 40,
        changes=[Change(operation="add", path="docs/a.txt", result_text="safe\n")],
        review_diff="safe diff\n",
    )
    loaded = store.load("return-002", expected_change_set_digest=written.change_set_digest)
    assert loaded.change_set_digest == written.change_set_digest
    assert loaded.review_diff == "safe diff\n"

    (root / "return-002" / "payload" / "000.txt").write_text("tampered\n")
    with pytest.raises(ArtifactError, match="ARTIFACT_INVALID"):
        store.load("return-002", expected_change_set_digest=written.change_set_digest)


def test_artifact_store_enforces_file_payload_and_diff_bounds(tmp_path: Path) -> None:
    ArtifactError, Store, Change = _api()
    store = Store(tmp_path / "provider-returns")

    six = [Change(operation="add", path=f"docs/{index}.txt", result_text="x") for index in range(6)]
    with pytest.raises(ArtifactError, match="TOO_MANY_FILES"):
        store.write(return_id="too-many", base_commit="a" * 40, changes=six, review_diff="")

    with pytest.raises(ArtifactError, match="FILE_TOO_LARGE"):
        store.write(
            return_id="large-file",
            base_commit="a" * 40,
            changes=[Change(operation="add", path="docs/large.txt", result_text="x" * 65537)],
            review_diff="",
        )

    payload = "x" * 60000
    five_large = [
        Change(operation="add", path=f"docs/{index}.txt", result_text=payload)
        for index in range(5)
    ]
    with pytest.raises(ArtifactError, match="PAYLOAD_TOO_LARGE"):
        store.write(
            return_id="large-total",
            base_commit="a" * 40,
            changes=five_large,
            review_diff="",
        )

    with pytest.raises(ArtifactError, match="DIFF_TOO_LARGE"):
        store.write(
            return_id="large-diff",
            base_commit="a" * 40,
            changes=[Change(operation="add", path="docs/a.txt", result_text="x")],
            review_diff="d" * 131073,
        )
