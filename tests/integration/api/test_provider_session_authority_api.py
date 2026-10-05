from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.handoffs.models import HandoffPrepareRequest


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _approved_provider_handoff(
    client: TestClient,
    headers: dict[str, str],
    *,
    provider: str,
) -> str:
    template_id = {
        "codex": "picotoopet-repo-maintenance-codex-v1",
        "claude_code": "picotoopet-repo-maintenance-claude-code-v1",
    }[provider]
    prepared = client.app.state.services.handoffs.prepare(
        HandoffPrepareRequest(
            template_id=template_id,
            title=f"Core-owned {provider} fixture",
            objective="Only Mac Core may turn this approved Handoff into a Provider Session.",
            expires_seconds=1800,
        ),
        idempotency_key=f"authority-prepare-{provider}",
    )
    submitted = client.post(
        f"/api/v1/handoffs/{prepared.handoff_id}/submit-approval",
        headers={**headers, "Idempotency-Key": f"authority-submit-{provider}"},
    )
    assert submitted.status_code == 200
    approval = client.get("/api/v1/approvals?limit=20", headers=headers).json()[0]
    approved = client.post(
        f"/api/v1/approvals/{approval['approval_id']}/decision",
        headers={**headers, "Idempotency-Key": f"authority-approve-{provider}"},
        json={
            "decision": "approve",
            "request_digest": approval["request_digest"],
            "reason": "Approve the bounded Handoff, not direct device Session creation.",
        },
    )
    assert approved.status_code == 200
    confirmation = client.post(
        f"/api/v1/handoffs/{prepared.handoff_id}/provider-usage-confirmation",
        headers={**headers, "Idempotency-Key": f"authority-usage-{provider}"},
        json={"status": "confirmed_available"},
    )
    assert confirmation.status_code == 201
    assert confirmation.json()["provider"] == provider
    return prepared.handoff_id


@pytest.mark.parametrize(
    ("provider", "route_suffix"),
    [
        ("codex", "codex"),
        ("claude_code", "claude-code"),
    ],
)
def test_device_token_cannot_create_coding_provider_session(
    tmp_path: Path,
    provider: str,
    route_suffix: str,
) -> None:
    client, headers = _client(tmp_path)
    with client:
        handoff_id = _approved_provider_handoff(client, headers, provider=provider)
        response = client.post(
            f"/api/v1/handoffs/{handoff_id}/provider-sessions/{route_suffix}",
            headers={**headers, "Idempotency-Key": f"forbidden-create-{provider}"},
        )
        openapi = client.app.openapi()

    assert response.status_code == 404
    assert (
        f"/api/v1/handoffs/{{handoff_id}}/provider-sessions/{route_suffix}"
        not in openapi["paths"]
    )
