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


def approve_codex_handoff(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    prepared = client.post(
        "/api/v1/handoffs/prepare",
        headers={**headers, "Idempotency-Key": "provider-handoff-prepare"},
        json={
            "template_id": "picotoopet-repo-maintenance-codex-v1",
            "title": "受控 Codex 修复",
            "objective": "只修改批准范围并返回本地可验证结果。",
            "expires_seconds": 1800,
        },
    )
    assert prepared.status_code == 201
    handoff = prepared.json()
    submitted = client.post(
        f"/api/v1/handoffs/{handoff['handoff_id']}/submit-approval",
        headers={**headers, "Idempotency-Key": "provider-handoff-submit"},
    )
    assert submitted.status_code == 200
    approval = client.get("/api/v1/approvals?limit=20", headers=headers).json()[0]
    approved = client.post(
        f"/api/v1/approvals/{approval['approval_id']}/decision",
        headers={**headers, "Idempotency-Key": "provider-handoff-approve"},
        json={
            "decision": "approve",
            "request_digest": approval["request_digest"],
            "reason": "批准一次低预算 Codex Session。",
        },
    )
    assert approved.status_code == 200
    final = client.get(
        f"/api/v1/handoffs/{handoff['handoff_id']}",
        headers=headers,
    )
    assert final.json()["status"] == "approved"
    return final.json()


def test_confirm_usage_and_create_one_codex_session(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = approve_codex_handoff(client, headers)
        confirmation = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-usage-confirmation",
            headers={**headers, "Idempotency-Key": "provider-usage-confirm"},
            json={"status": "confirmed_available"},
        )
        replay_confirmation = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-usage-confirmation",
            headers={**headers, "Idempotency-Key": "provider-usage-confirm"},
            json={"status": "confirmed_available"},
        )
        created = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-sessions/codex",
            headers={**headers, "Idempotency-Key": "provider-session-create"},
        )
        replay_created = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-sessions/codex",
            headers={**headers, "Idempotency-Key": "provider-session-create"},
        )
        listed = client.get("/api/v1/provider-sessions?limit=100", headers=headers)
        fetched = client.get(
            f"/api/v1/provider-sessions/{created.json()['session_id']}",
            headers=headers,
        )

    assert confirmation.status_code == 201
    assert replay_confirmation.json() == confirmation.json()
    assert confirmation.json()["provider"] == "codex"
    assert confirmation.json()["budget"] == {
        "max_turns": 8,
        "timeout_seconds": 900,
        "max_changed_files": 5,
        "max_file_bytes": 65536,
        "max_return_bytes": 262144,
        "automatic_retries": 0,
        "concurrency": 1,
        "network_tools_allowed": False,
    }
    assert created.status_code == 201
    assert replay_created.json() == created.json()
    assert created.json()["status"] == "waiting_provider_ready"
    assert listed.json() == [created.json()]
    assert fetched.json() == created.json()
    text = created.text.lower()
    for forbidden in ("token", "cookie", "authorization", "api_key", "transcript"):
        assert forbidden not in text


def test_provider_api_rejects_arbitrary_body_and_low_usage(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        handoff = approve_codex_handoff(client, headers)
        arbitrary_confirmation = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-usage-confirmation",
            headers={**headers, "Idempotency-Key": "provider-arbitrary-confirm"},
            json={"status": "confirmed_available", "model_name": "arbitrary"},
        )
        low = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-usage-confirmation",
            headers={**headers, "Idempotency-Key": "provider-low-confirm"},
            json={"status": "confirmed_low"},
        )
        denied = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-sessions/codex",
            headers={**headers, "Idempotency-Key": "provider-low-session"},
        )
        arbitrary_create = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-sessions/codex",
            headers={**headers, "Idempotency-Key": "provider-body-session"},
            json={"command": "do anything"},
        )

    assert arbitrary_confirmation.status_code == 422
    assert low.status_code == 201
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "PROVIDER_POLICY_DENIED"
    assert arbitrary_create.status_code == 422


def test_provider_api_requires_authentication_and_idempotency(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        status = client.get("/api/v1/providers/codex/status")
        handoff = approve_codex_handoff(client, headers)
        missing_key = client.post(
            f"/api/v1/handoffs/{handoff['handoff_id']}/provider-usage-confirmation",
            headers=headers,
            json={"status": "confirmed_available"},
        )

    assert status.status_code == 401
    assert missing_key.status_code == 422
