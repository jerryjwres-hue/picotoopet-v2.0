from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def prepare_handoff(
    client: TestClient,
    headers: dict[str, str],
    *,
    key: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/handoffs/prepare",
        headers={**headers, "Idempotency-Key": f"{key}-prepare"},
        json={
            "template_id": "picotoopet-repo-maintenance-v1",
            "title": "Mock Dev Broker",
            "objective": "验证固定沙盒、超时取消和 Return 导回。",
            "expires_seconds": 1800,
        },
    )
    assert response.status_code == 201
    return response.json()


def approve_handoff(
    client: TestClient,
    headers: dict[str, str],
    handoff: dict[str, object],
    *,
    key: str,
) -> None:
    submitted = client.post(
        f"/api/v1/handoffs/{handoff['handoff_id']}/submit-approval",
        headers={**headers, "Idempotency-Key": f"{key}-submit"},
    )
    assert submitted.status_code == 200
    approval = client.get("/api/v1/approvals?limit=20", headers=headers).json()[0]
    decided = client.post(
        f"/api/v1/approvals/{approval['approval_id']}/decision",
        headers={**headers, "Idempotency-Key": f"{key}-approve"},
        json={
            "decision": "approve",
            "request_digest": approval["request_digest"],
            "reason": "批准固定 Mock Broker 沙盒验证。",
        },
    )
    assert decided.status_code == 200


def test_reserve_start_list_get_and_cancel_broker_session(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = prepare_handoff(client, headers, key="broker-api-flow")
        unapproved = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/broker-sessions/mock",
            headers={**headers, "Idempotency-Key": "broker-api-unapproved"},
        )
        approve_handoff(client, headers, handoff, key="broker-api-flow")
        endpoint = f"/api/v1/handoffs/{handoff['handoff_id']}/broker-sessions/mock"
        write_headers = {**headers, "Idempotency-Key": "broker-api-session"}
        created = client.post(endpoint, headers=write_headers)
        replay = client.post(endpoint, headers=write_headers)
        payload = created.json()
        session = payload["record"]
        session_id = session["session_id"]
        started = client.post(
            f"/api/v1/broker-sessions/{session_id}/start",
            headers={**headers, "Idempotency-Key": "broker-api-start"},
        )
        listed = client.get("/api/v1/broker-sessions?limit=100", headers=headers)
        fetched = client.get(f"/api/v1/broker-sessions/{session_id}", headers=headers)
        cancelled = client.post(
            f"/api/v1/broker-sessions/{session_id}/cancel",
            headers={**headers, "Idempotency-Key": "broker-api-cancel"},
        )

    assert unapproved.status_code == 400
    assert unapproved.json()["error"]["code"] == "BROKER_POLICY_DENIED"
    assert created.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == payload
    assert session["status"] == "reserved"
    assert session["provider"] == "local-mock-dev-broker"
    assert session["timeout_seconds"] == 30
    assert len(payload["capability"]) == 64
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert listed.status_code == 200
    assert "capability" not in listed.text.lower()
    assert fetched.json()["session_id"] == session_id
    assert "capability" not in fetched.text.lower()
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_broker_state_commands_reject_body_and_missing_idempotency(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = prepare_handoff(client, headers, key="broker-api-body")
        approve_handoff(client, headers, handoff, key="broker-api-body")
        endpoint = f"/api/v1/handoffs/{handoff['handoff_id']}/broker-sessions/mock"
        missing_key = client.post(endpoint, headers=headers)
        arbitrary_body = client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "broker-api-body-session"},
            json={"path": "../outside", "command": "powershell"},
        )

    assert missing_key.status_code == 422
    assert arbitrary_body.status_code == 422
    assert "outside" not in arbitrary_body.text
    assert "powershell" not in arbitrary_body.text.lower()


def test_broker_return_rejects_wrong_media_type_and_oversize_before_parsing(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        wrong_media = client.post(
            "/api/v1/broker-sessions/00000000-0000-0000-0000-000000000000/return",
            headers={
                **headers,
                "Idempotency-Key": "broker-api-media",
                "X-Picotoo-Broker-Session": "0" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"{}",
        )
        oversized = client.post(
            "/api/v1/broker-sessions/00000000-0000-0000-0000-000000000000/return",
            headers={
                **headers,
                "Idempotency-Key": "broker-api-large",
                "X-Picotoo-Broker-Session": "0" * 64,
                "Content-Type": "application/json",
            },
            content=b'"' + (b"x" * (128 * 1024 + 1)) + b'"',
        )

    assert wrong_media.status_code == 415
    assert wrong_media.json()["error"]["code"] == "BROKER_OUTPUT_INVALID"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "BROKER_OUTPUT_TOO_LARGE"
