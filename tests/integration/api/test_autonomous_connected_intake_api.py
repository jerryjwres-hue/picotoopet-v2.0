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


def _legacy_db(path: Path) -> bytes:
    connection = sqlite3.connect(path)
    try:
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

        imports_root = paths.autonomous_staging_dir / "legacy-4.1-imports"
        assert not imports_root.exists() or not list(imports_root.iterdir())
