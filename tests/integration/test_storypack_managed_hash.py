"""Only Mac Core-managed object bytes are eligible for read-only integrity checks."""

import hashlib

import pytest

from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs


def _register_asset(database, asset_id, *, sha256, stored_object_hash=None, source_path=None):
    # 所有测试记录写在 pytest tmp_path 数据库中，不涉及生产 SQLite。
    database.execute(
        """INSERT OR IGNORE INTO projects
           (project_id, title, project_type, source_app, classification, status,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "asset-test-project", "Asset fixture", "pet", "test", "internal", "Active",
            "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z",
        ),
    )
    database.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, artifact_type, classification, sha256,
            stored_object_hash, source_path, is_original, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            asset_id, "asset-test-project", "image", "internal", sha256,
            stored_object_hash, source_path, 1, "2026-11-19T00:00:00Z",
        ),
    )


def _check(services, ref):
    return inspect_recorded_asset_refs(
        services.database, [ref], managed_objects_dir=services.settings.paths.objects_dir
    )[0]


def test_matching_managed_bytes_are_still_not_owner_approved(api):
    services = api.app.state.services
    stored = services.results.put_bytes(b"synthetic fixture image bytes", result_type="image")
    _register_asset(
        services.database, "maotai_master_v1",
        sha256=stored.object_hash, stored_object_hash=stored.object_hash,
    )
    record = _check(services, "maotai_master_v1")
    assert record["managed_object_integrity"] == "CONTENT_VERIFIED_UNAPPROVED"
    assert record["content_integrity_verified"] is True
    assert record["physical_file_verified"] is True
    assert record["owner_approval_verified"] is False
    assert record["usable_for_generation"] is False
    response = api.post("/api/v1/studio/storypacks/preview", json=_storypack())
    assert response.status_code == 200
    assert response.json()["asset_record_checks"][0]["content_integrity_verified"] is True
    assert response.json()["can_queue"] is False
    assert services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_tampered_managed_object_does_not_pass(api):
    services = api.app.state.services
    stored = services.results.put_bytes(b"before", result_type="image")
    _register_asset(
        services.database, "tampered_v1",
        sha256=stored.object_hash, stored_object_hash=stored.object_hash,
    )
    stored.object_path.write_bytes(b"after")
    record = _check(services, "tampered_v1")
    assert record["managed_object_integrity"] == "CONTENT_HASH_MISMATCH"
    assert record["content_integrity_verified"] is False


def test_external_path_is_never_used_as_fallback(api, tmp_path):
    services = api.app.state.services
    source = tmp_path / "outside.txt"
    source.write_bytes(b"outside source bytes")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _register_asset(
        services.database, "external_v1",
        sha256=digest, stored_object_hash=None, source_path=str(source),
    )
    status = _check(services, "external_v1")
    assert status["managed_object_integrity"] == "NO_MANAGED_OBJECT"
    assert status["content_integrity_verified"] is False


def test_conflicting_digest_or_invalid_storage_key_blocks(api):
    services = api.app.state.services
    stored = services.results.put_bytes(b"safe content", result_type="image")
    _register_asset(
        services.database, "conflict_v1",
        sha256="a" * 64, stored_object_hash=stored.object_hash,
    )
    _register_asset(
        services.database, "badpath_v1",
        sha256=stored.object_hash, stored_object_hash="../outside",
    )
    assert _check(services, "conflict_v1")["managed_object_integrity"] == "DIGEST_CONFLICT"
    assert _check(services, "badpath_v1")["managed_object_integrity"] == "BAD_OBJECT_DIGEST"
    _register_asset(
        services.database, "wrongtype_v1",
        sha256=stored.object_hash, stored_object_hash=12345,
    )
    assert _check(services, "wrongtype_v1")["managed_object_integrity"] == (
        "BAD_OBJECT_DIGEST"
    )


def test_missing_or_symlinked_managed_file_blocks(api, tmp_path):
    services = api.app.state.services
    missing = hashlib.sha256(b"not written").hexdigest()
    _register_asset(
        services.database, "missing_v1",
        sha256=missing, stored_object_hash=missing,
    )
    assert _check(services, "missing_v1")["managed_object_integrity"] == "OBJECT_NOT_FOUND"

    stored = services.results.put_bytes(b"verified input", result_type="image")
    _register_asset(
        services.database, "symlink_v1",
        sha256=stored.object_hash, stored_object_hash=stored.object_hash,
    )
    outside = tmp_path / "outside-object"
    outside.write_bytes(b"verified input")
    stored.object_path.unlink()
    try:
        stored.object_path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("host does not support symlinks")
    result = _check(services, "symlink_v1")
    assert result["managed_object_integrity"] == "OBJECT_SYMLINK_BLOCKED"
    assert result["content_integrity_verified"] is False


def test_bounded_hashing_never_exceeds_preview_limit(api, monkeypatch):
    from picotoopet_core.domain import storypack_assets

    services = api.app.state.services
    stored = services.results.put_bytes(b"1234567890", result_type="image")
    _register_asset(
        services.database, "budget_v1",
        sha256=stored.object_hash, stored_object_hash=stored.object_hash,
    )
    monkeypatch.setattr(storypack_assets, "_MAX_PREVIEW_BYTES", 5)
    assert _check(services, "budget_v1")["managed_object_integrity"] == (
        "VERIFY_BUDGET_EXCEEDED"
    )
    monkeypatch.setattr(storypack_assets, "_MAX_FILE_BYTES", 5)
    assert _check(services, "budget_v1")["managed_object_integrity"] == (
        "OBJECT_TOO_LARGE_FOR_PREVIEW"
    )


@pytest.fixture
def api(tmp_path):
    import secrets

    from fastapi.testclient import TestClient

    from picotoopet_core.api.app import create_app
    from picotoopet_core.config.models import AppSettings
    from picotoopet_core.config.paths import RuntimePaths

    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _storypack():
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "E02",
        "title": "Verification fixture",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "story": {"goal": "Reach dinner", "payoff": "Enjoy dinner"},
        "shots": [{
            "id": "S01", "action": "Walk", "state_in": "Stand",
            "state_out": "Door", "because": "Story progression",
        }],
    }
