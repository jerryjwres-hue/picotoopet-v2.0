from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


TOKEN = "0123456789abcdef0123456789abcdef"
EXTENSION_ID = "miagfkomnofgeeahbficblhlcgahaldp"


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str], RuntimePaths]:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    settings = AppSettings(paths=paths, api_token=TOKEN)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {TOKEN}"}, paths


def _create_legacy_schema(connection: sqlite3.Connection) -> None:
    # ── Shared fixture schema mirrors the supported Maotai OS 4.1 compatibility tables. ──
    connection.executescript(
        """
        CREATE TABLE canonical_products (
            product_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            brand TEXT DEFAULT '',
            category TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE consumer_signals (
            signal_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            source_product_key TEXT,
            source TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            source_signal_id TEXT DEFAULT '',
            rating REAL,
            original_text TEXT NOT NULL,
            signal_date TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            signal_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            imported_at TEXT NOT NULL
        );
        """
    )


def _legacy_db(path: Path) -> bytes:
    connection = sqlite3.connect(path)
    try:
        _create_legacy_schema(connection)
        connection.execute(
            "INSERT INTO canonical_products VALUES (?, ?, '', '', ?, ?)",
            ("p1", "Large Dog Chew Toy", "2026-08-01", "2026-08-01"),
        )
        connection.execute(
            "INSERT INTO consumer_signals VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)",
            (
                "s1",
                "p1",
                "amazon",
                "review",
                "review-1",
                4.0,
                "Handle is too small for my malamute.",
                "2026-07-20",
                "https://www.amazon.com/dp/B0ABCDEFGHI",
                "legacy-hash",
                "2026-08-01",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return path.read_bytes()


def _legacy_db_many(path: Path, *, product_count: int) -> bytes:
    connection = sqlite3.connect(path)
    try:
        _create_legacy_schema(connection)
        for index in range(1, product_count + 1):
            product_id = f"p{index:02d}"
            signal_id = f"s{index:02d}"
            connection.execute(
                "INSERT INTO canonical_products VALUES (?, ?, '', '', ?, ?)",
                (
                    product_id,
                    f"Large Dog Product {index:02d}",
                    "2026-08-01",
                    "2026-08-01",
                ),
            )
            connection.execute(
                "INSERT INTO consumer_signals VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)",
                (
                    signal_id,
                    product_id,
                    "amazon",
                    "review",
                    f"review-{index:02d}",
                    4.0,
                    f"Consumer evidence for product {index:02d}.",
                    "2026-07-20",
                    f"https://www.amazon.com/dp/B0TEST{index:05d}",
                    f"legacy-hash-{index:02d}",
                    "2026-08-01",
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return path.read_bytes()


def _visible_auto_goals(client: TestClient, headers: dict[str, str]) -> list[dict[str, object]]:
    # ── Product-visible autonomous intake Goals share the existing Goal Center surface. ──
    response = client.get("/api/v1/autonomous/goals", headers=headers)
    assert response.status_code == 200
    return [item for item in response.json() if item["origin"] == "autonomous"]


def test_browser_bridge_intake_is_authenticated_and_persists_canonical_evidence(
    tmp_path: Path,
) -> None:
    client, headers, _paths = _client(tmp_path)
    packet = {
        "type": "capture_page",
        "extension_id": EXTENSION_ID,
        "url": "https://www.amazon.com/dp/B0ABCDEFGHI",
        "page": {
            "product_title": "Large Dog Chew Toy",
            "rating": "4.6",
            "review_count": "1,234",
            "visible_signals": [
                {"source_id": "review-1", "text": "Handle is too small for my malamute."}
            ],
        },
    }
    with client:
        path = "/api/v1/autonomous/browser-captures"
        assert client.post(path, json=packet).status_code == 401
        created = client.post(
            path,
            headers={**headers, "Idempotency-Key": "browser-api-1"},
            json=packet,
        )
        assert created.status_code == 201
        assert created.json()["evidence_count"] == 2
        assert created.json()["platform"] == "amazon"
        assert "cookie" not in created.text.lower()
        assert client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM autonomous_evidence"
        ) == 2

        # ── New connected evidence must immediately materialize one bounded P2 Goal. ──
        auto_goals = _visible_auto_goals(client, headers)
        assert len(auto_goals) == 1
        auto_goal = auto_goals[0]
        assert auto_goal["intent_type"] == "product.research_to_video"
        assert auto_goal["priority_class"] == "P2"
        assert auto_goal["constraints"]["read_only_research"] is True
        assert auto_goal["constraints"]["product_visible"] is True
        assert auto_goal["constraints"]["auto_trigger_source"] == "browser_bridge"
        assert auto_goal["constraints"]["connected_product_keys"] == [
            created.json()["product_key"]
        ]
        assert auto_goal["workflow_id"]

        workflow = client.app.state.services.workflows.get_workflow(str(auto_goal["workflow_id"]))
        assert [step.task_type for step in workflow.steps] == [
            "autonomous.discovery.v1",
            "autonomous.goal_synthesis.v1",
            "autonomous.goal_handoff.v1",
        ]
        assert workflow.steps[0].payload["connected_product_keys"] == [
            created.json()["product_key"]
        ]

        replay = client.post(
            path,
            headers={**headers, "Idempotency-Key": "browser-api-1"},
            json=packet,
        )
        assert replay.status_code == 201
        assert replay.json()["capture_id"] == created.json()["capture_id"]
        assert client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM autonomous_evidence"
        ) == 2
        # ── Replaying the same intake event must not create a second Goal or Workflow. ──
        assert len(_visible_auto_goals(client, headers)) == 1


def test_browser_bridge_intake_rejects_secret_payload(tmp_path: Path) -> None:
    client, headers, _paths = _client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/autonomous/browser-captures",
            headers={**headers, "Idempotency-Key": "browser-secret"},
            json={
                "type": "capture_page",
                "extension_id": EXTENSION_ID,
                "url": "https://www.amazon.com/dp/B0ABCDEFGHI",
                "page": {"title": "safe", "cookie": "must-not-enter-core"},
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BROWSER_CAPTURE_REJECTED"
        assert client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM autonomous_evidence"
        ) == 0
        # ── Rejected evidence can never trigger autonomous analysis. ──
        assert _visible_auto_goals(client, headers) == []


def test_legacy_41_database_upload_is_streamed_into_managed_staging_and_imported(
    tmp_path: Path,
) -> None:
    client, headers, paths = _client(tmp_path)
    source = tmp_path / "legacy.db"
    payload = _legacy_db(source)
    with client:
        response = client.post(
            "/api/v1/autonomous/legacy-4.1/import",
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "X-Picotoo-Source-Name": "Maotai-4.1.db",
            },
            content=payload,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "completed"
        assert body["products_imported"] == 1
        assert body["evidence_imported"] == 1
        assert body["source_name"] == "Maotai-4.1.db"
        assert "source_path" not in body
        assert client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM autonomous_evidence"
        ) == 1

        # ── One completed legacy import becomes one bounded visible analysis Goal. ──
        auto_goals = _visible_auto_goals(client, headers)
        assert len(auto_goals) == 1
        auto_goal = auto_goals[0]
        assert auto_goal["intent_type"] == "product.research_to_video"
        assert auto_goal["priority_class"] == "P2"
        assert auto_goal["constraints"]["auto_trigger_source"] == "maotai41_import"
        assert auto_goal["constraints"]["connected_product_keys"] == ["legacy41:p1"]
        assert auto_goal["workflow_id"]

        imports_root = paths.autonomous_staging_dir / "legacy-4.1-imports"
        assert not imports_root.exists() or not list(imports_root.iterdir())


def test_large_legacy_import_batches_every_product_into_bounded_auto_goals(tmp_path: Path) -> None:
    client, headers, _paths = _client(tmp_path)
    source = tmp_path / "legacy-many.db"
    payload = _legacy_db_many(source, product_count=9)

    with client:
        response = client.post(
            "/api/v1/autonomous/legacy-4.1/import",
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "X-Picotoo-Source-Name": "Maotai-4.1-many.db",
            },
            content=payload,
        )
        assert response.status_code == 201
        assert response.json()["products_imported"] == 9
        assert response.json()["evidence_imported"] == 9

        auto_goals = _visible_auto_goals(client, headers)
        assert len(auto_goals) == 2
        batches = [goal["constraints"]["connected_product_keys"] for goal in auto_goals]
        assert all(1 <= len(batch) <= 8 for batch in batches)
        assert sorted(key for batch in batches for key in batch) == [
            f"legacy41:p{index:02d}" for index in range(1, 10)
        ]
        assert all(goal["priority_class"] == "P2" for goal in auto_goals)
        assert all(goal["constraints"]["auto_trigger_source"] == "maotai41_import" for goal in auto_goals)

        # ── Every batch must still use the frozen three-stage pipeline. ──
        for goal in auto_goals:
            workflow = client.app.state.services.workflows.get_workflow(str(goal["workflow_id"]))
            assert [step.task_type for step in workflow.steps] == [
                "autonomous.discovery.v1",
                "autonomous.goal_synthesis.v1",
                "autonomous.goal_handoff.v1",
            ]
            assert workflow.steps[0].payload["connected_product_keys"] == goal["constraints"][
                "connected_product_keys"
            ]

        replay = client.post(
            "/api/v1/autonomous/legacy-4.1/import",
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "X-Picotoo-Source-Name": "Maotai-4.1-many.db",
            },
            content=payload,
        )
        assert replay.status_code == 201
        # ── Replaying the same backup must keep the exact same two Goals. ──
        assert len(_visible_auto_goals(client, headers)) == 2
