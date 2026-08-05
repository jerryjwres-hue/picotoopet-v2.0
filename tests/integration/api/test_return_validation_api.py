from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def approve_handoff(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    prepared = client.post(
        "/api/v1/handoffs/prepare",
        headers={**headers, "Idempotency-Key": "return-api-prepare"},
        json={
            "template_id": "picotoopet-repo-maintenance-v1",
            "title": "运行 Return 合同验证",
            "objective": "验证本地零变更 Return，不启动 Provider。",
            "expires_seconds": 1800,
        },
    ).json()
    client.post(
        f"/api/v1/handoffs/{prepared['handoff_id']}/submit-approval",
        headers={**headers, "Idempotency-Key": "return-api-submit"},
    )
    approval = client.get("/api/v1/approvals?limit=20", headers=headers).json()[0]
    response = client.post(
        f"/api/v1/approvals/{approval['approval_id']}/decision",
        headers={**headers, "Idempotency-Key": "return-api-approve"},
        json={
            "decision": "approve",
            "request_digest": approval["request_digest"],
            "reason": "批准本地 Return 合同演练。",
        },
    )
    assert response.status_code == 200
    return client.get(
        f"/api/v1/handoffs/{prepared['handoff_id']}",
        headers=headers,
    ).json()


def test_run_list_and_get_bounded_return_self_test(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = approve_handoff(client, headers)
        endpoint = f"/api/v1/handoffs/{handoff['handoff_id']}/returns/self-test"
        write_headers = {**headers, "Idempotency-Key": "return-api-self-test"}
        created = client.post(endpoint, headers=write_headers)
        replay = client.post(endpoint, headers=write_headers)
        item = created.json()
        listed = client.get("/api/v1/returns?limit=100", headers=headers)
        fetched = client.get(f"/api/v1/returns/{item['return_id']}", headers=headers)

    assert created.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == item
    assert item["handoff_id"] == handoff["handoff_id"]
    assert item["status"] == "contract_validated"
    assert item["provider"] == "local-contract-self-test"
    assert item["changed_file_count"] == 0
    assert item["event_count"] == 3
    assert len(item["manifest_digest"]) == 64
    assert item["quarantine_code"] is None
    assert all(check["passed"] for check in item["validation_checks"])
    assert len(item["event_summaries"]) == 3
    assert listed.status_code == 200
    assert listed.json()[0] == item
    assert fetched.json() == item
    serialized = created.text.lower()
    for forbidden in (
        "authorization",
        "bearer",
        "token",
        "password",
        "session_events.ndjson",
        "return_manifest.json",
        "d:/picotoopet",
        "diff.patch",
    ):
        assert forbidden not in serialized


def test_return_write_requires_idempotency_and_approved_handoff(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        prepared = client.post(
            "/api/v1/handoffs/prepare",
            headers={**headers, "Idempotency-Key": "return-api-unapproved-prepare"},
            json={
                "template_id": "picotoopet-repo-maintenance-v1",
                "title": "尚未批准",
                "objective": "Return 演练必须等待 Handoff 批准。",
                "expires_seconds": 1800,
            },
        ).json()
        missing_key = client.post(
            f"/api/v1/handoffs/{prepared['handoff_id']}/returns/self-test",
            headers=headers,
        )
        unapproved = client.post(
            f"/api/v1/handoffs/{prepared['handoff_id']}/returns/self-test",
            headers={**headers, "Idempotency-Key": "return-api-unapproved"},
        )

    assert missing_key.status_code == 422
    assert unapproved.status_code == 400
    assert unapproved.json()["error"]["code"] == "RETURN_POLICY_DENIED"


def test_return_api_has_no_upload_or_arbitrary_payload_surface(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = approve_handoff(client, headers)
        endpoint = f"/api/v1/handoffs/{handoff['handoff_id']}/returns/self-test"
        arbitrary_json = client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "return-api-arbitrary-json"},
            json={
                "path": "../outside",
                "command": "powershell -ExecutionPolicy Bypass",
                "manifest": {"provider": "external"},
            },
        )
        multipart = client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "return-api-multipart"},
            files={"file": ("return.zip", b"PK\x03\x04", "application/zip")},
        )

    assert arbitrary_json.status_code == 422
    assert multipart.status_code == 422
