from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db import database as database_module
from picotoopet_core.db.database import Database

TOKEN = "0123456789abcdef0123456789abcdef"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=TOKEN)
    return create_app(settings), {"Authorization": f"Bearer {TOKEN}"}


def _goal(database) -> str:  # type: ignore[no-untyped-def]
    goal_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    database.execute(
        "INSERT INTO autonomous_goals(goal_id,origin,intent_type,priority_class,objective,"
        "constraints_json,budget_class,status,idempotency_key,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            goal_id,
            "operator",
            "video",
            "P2",
            "obj",
            "{}",
            "free",
            "ready",
            f"g-{goal_id}",
            now,
            now,
        ),
    )
    return goal_id


def _project(database) -> str:  # type: ignore[no-untyped-def]
    project_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    database.execute(
        "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?)",
        (project_id, "t", "x", "app", "INTERNAL", None, "active", now, now),
    )
    return project_id


def _body(scope_id: str, **overrides):  # type: ignore[no-untyped-def]
    body = {
        "scope_kind": "autonomous_goal",
        "scope_id": scope_id,
        "idempotency_key": "import-1",
        "sha256": SHA_A,
        "size_bytes": 1234,
        "media_type": "image/png",
        "width": 640,
        "height": 360,
        "duration_ms": None,
        "managed_root_id": "windows.comfy-input.v1",
        "source_kind": "windows_user_import.v1",
    }
    body.update(overrides)
    return body


def test_register_derives_scope_key_relpath_and_no_path_authority(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        goal = _goal(app.state.services.database)
        response = client.post("/api/v1/assets", headers=headers, json=_body(goal))
        assert response.status_code == 200
        record = response.json()
        assert record["scope_key"] == f"autonomous-goal:{goal}"
        assert record["managed_relpath"] == f"PicotooPet/assets/v1/aa/{SHA_A}.png"
        assert record["managed_root_id"] == "windows.comfy-input.v1"
        assert record["duration_ms"] is None
        assert record["cloud_policy"] == "local_only"
        assert record["provenance"]["bytes_in_core"] is False
        row = app.state.services.database.fetchone(
            "SELECT source_path,stored_object_hash FROM artifacts WHERE artifact_id=?",
            (record["asset_id"],),
        )
        assert row["source_path"] is None and row["stored_object_hash"] is None

        jpeg = client.post(
            "/api/v1/assets",
            headers=headers,
            json=_body(goal, idempotency_key="import-2", sha256=SHA_B, media_type="image/jpeg"),
        ).json()
        assert jpeg["managed_relpath"] == f"PicotooPet/assets/v1/bb/{SHA_B}.jpg"


def test_project_scope_requires_existing_owner(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        project = _project(app.state.services.database)
        ok = client.post(
            "/api/v1/assets", headers=headers, json=_body(project, scope_kind="project")
        )
        assert ok.status_code == 200 and ok.json()["scope_key"] == f"project:{project}"
        missing = client.post("/api/v1/assets", headers=headers, json=_body(str(uuid4())))
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TRUSTED_ASSET_SCOPE_NOT_FOUND"


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope_kind": "task"},
        {"managed_root_id": "windows.other.v1"},
        {"source_kind": "mac_import.v1"},
        {"media_type": "image/gif"},
        {"media_type": "video/mp4"},
        {"duration_ms": 1000},
        {"width": 0},
        {"height": -1},
        {"width": 20000},
        {"sha256": "A" * 64},
        {"sha256": "abc"},
        {"size_bytes": 0},
        {"size_bytes": 10**9},
        {"asset_id": "x"},
        {"managed_relpath": "evil/path.png"},
        {"source_path": "C:\\Users\\me\\a.png"},
        {"absolute_path": "/etc/passwd"},
        {"url": "http://example.com/a.png"},
        {"endpoint": "http://x"},
        {"executable": "cmd.exe"},
        {"workflow": {}},
        {"model": "m"},
    ],
)
def test_invalid_or_forbidden_request_is_rejected(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        goal = _goal(app.state.services.database)
        response = client.post("/api/v1/assets", headers=headers, json=_body(goal, **overrides))
        assert response.status_code == 422
        assert (
            app.state.services.database.scalar(
                "SELECT COUNT(*) FROM artifacts WHERE source_kind IS NOT NULL"
            )
            == 0
        )


def test_idempotent_replay_conflict_and_dedupe(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        goal = _goal(app.state.services.database)
        first = client.post("/api/v1/assets", headers=headers, json=_body(goal)).json()
        assert client.post("/api/v1/assets", headers=headers, json=_body(goal)).json() == first

        changed = client.post("/api/v1/assets", headers=headers, json=_body(goal, size_bytes=999))
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "TRUSTED_ASSET_IDEMPOTENCY_CONFLICT"

        deduped = client.post(
            "/api/v1/assets", headers=headers, json=_body(goal, idempotency_key="another-key")
        ).json()
        assert deduped["asset_id"] == first["asset_id"]
        assert deduped["created_at"] == first["created_at"]

        fact_conflict = client.post(
            "/api/v1/assets",
            headers=headers,
            json=_body(goal, idempotency_key="third-key", width=641),
        )
        assert fact_conflict.status_code == 409
        assert fact_conflict.json()["error"]["code"] == "TRUSTED_ASSET_FACT_CONFLICT"
        assert (
            app.state.services.database.scalar(
                "SELECT COUNT(*) FROM artifacts WHERE source_kind IS NOT NULL"
            )
            == 1
        )


def test_cross_scope_assets_are_isolated_and_responses_have_no_paths(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        database = app.state.services.database
        goal_a, goal_b = _goal(database), _goal(database)
        asset_a = client.post("/api/v1/assets", headers=headers, json=_body(goal_a)).json()
        asset_b = client.post(
            "/api/v1/assets", headers=headers, json=_body(goal_b, idempotency_key="import-b")
        ).json()
        assert asset_a["asset_id"] != asset_b["asset_id"]

        listed = client.get(
            "/api/v1/assets",
            headers=headers,
            params={"scope_kind": "autonomous_goal", "scope_id": goal_a},
        )
        assert [item["asset_id"] for item in listed.json()] == [asset_a["asset_id"]]

        own = client.get(
            f"/api/v1/assets/{asset_a['asset_id']}",
            headers=headers,
            params={"scope_kind": "autonomous_goal", "scope_id": goal_a},
        )
        assert own.status_code == 200
        cross = client.get(
            f"/api/v1/assets/{asset_a['asset_id']}",
            headers=headers,
            params={"scope_kind": "autonomous_goal", "scope_id": goal_b},
        )
        assert cross.status_code == 404
        assert cross.json()["error"]["code"] == "TRUSTED_ASSET_NOT_FOUND"
        half = client.get(
            f"/api/v1/assets/{asset_a['asset_id']}",
            headers=headers,
            params={"scope_kind": "project"},
        )
        assert half.status_code == 422

        unknown_scope = client.get(
            "/api/v1/assets",
            headers=headers,
            params={"scope_kind": "autonomous_goal", "scope_id": str(uuid4())},
        )
        assert unknown_scope.status_code == 404

        text = json.dumps([own.json(), listed.json()])
        for forbidden in ("source_path", "C:\\", "/Users/", "http://", "idempotency"):
            assert forbidden not in text


def test_assets_require_auth_and_legacy_artifacts_are_not_listed(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/assets", params={"scope_kind": "project", "scope_id": "x"}
            ).status_code
            == 401
        )
        assert client.post("/api/v1/assets", json={}).status_code == 401
        database = app.state.services.database
        project = _project(database)
        database.execute(
            "INSERT INTO artifacts(artifact_id,project_id,artifact_type,classification,"
            "source_path,created_at) "
            "VALUES ('legacy-1',?, 'doc','INTERNAL','/x/y',?)",
            (project, datetime.now(UTC).isoformat()),
        )
        assert client.get("/api/v1/assets/legacy-1", headers=headers).status_code == 404
        listed = client.get(
            "/api/v1/assets", headers=headers, params={"scope_kind": "project", "scope_id": project}
        )
        assert listed.json() == []


def test_migration_24_preserves_legacy_artifacts_and_dependents(tmp_path: Path) -> None:
    original = database_module.MIGRATION_024
    database_module.MIGRATION_024 = "SELECT 1;"
    database = Database(tmp_path / "core.db")
    try:
        database.open()
        database.apply_migrations()
        database.execute("DELETE FROM schema_migrations WHERE version=24")
    finally:
        database_module.MIGRATION_024 = original
    project = _project(database)
    database.execute(
        "INSERT INTO artifacts(artifact_id,project_id,artifact_type,classification,source_path,"
        "media_type,size_bytes,sha256,is_original,created_at) VALUES ('old-1',?,?,?,?,?,?,?,1,?)",
        (
            project,
            "doc",
            "INTERNAL",
            "/legacy/path",
            "text/plain",
            5,
            SHA_A,
            "2026-01-01T00:00:00+00:00",
        ),
    )
    database.execute(
        "INSERT INTO artifact_links VALUES ('old-1','old-1','self','2026-01-01T00:00:00+00:00')"
    )

    database.apply_migrations()
    database.apply_migrations()  # idempotent

    row = database.fetchone("SELECT * FROM artifacts WHERE artifact_id='old-1'")
    assert (row["project_id"], row["source_path"], row["sha256"], row["size_bytes"]) == (
        project,
        "/legacy/path",
        SHA_A,
        5,
    )
    assert row["scope_kind"] is None and row["managed_relpath"] is None
    assert database.scalar("SELECT COUNT(*) FROM artifact_links") == 1
    assert database.fetchall("PRAGMA foreign_key_check") == []
    assert database.scalar("PRAGMA foreign_keys") == 1
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 24
    columns = {item["name"]: item for item in database.fetchall("PRAGMA table_info(artifacts)")}
    assert columns["project_id"]["notnull"] == 0
    database.close()
