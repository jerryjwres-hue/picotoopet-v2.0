from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def prepare_payload() -> dict[str, object]:
    return {
        "template_id": "picotoopet-repo-maintenance-v1",
        "title": "准备下一阶段修复",
        "objective": "生成受控 Handoff 草稿并提交摘要绑定审批。",
        "expires_seconds": 1800,
    }


def test_prepare_list_get_submit_and_approve_handoff(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    prepare_headers = {**headers, "Idempotency-Key": "handoff-prepare-ui-001"}

    with client:
        templates = client.get("/api/v1/handoffs/templates", headers=headers)
        prepared = client.post(
            "/api/v1/handoffs/prepare",
            headers=prepare_headers,
            json=prepare_payload(),
        )
        replay = client.post(
            "/api/v1/handoffs/prepare",
            headers=prepare_headers,
            json=prepare_payload(),
        )
        item = prepared.json()
        listed = client.get("/api/v1/handoffs?limit=100", headers=headers)
        fetched = client.get(f"/api/v1/handoffs/{item['handoff_id']}", headers=headers)
        queue_before = client.get("/api/v1/status", headers=headers).json()["task_counts"]

        submitted = client.post(
            f"/api/v1/handoffs/{item['handoff_id']}/submit-approval",
            headers={**headers, "Idempotency-Key": "handoff-submit-ui-001"},
        )
        submit_replay = client.post(
            f"/api/v1/handoffs/{item['handoff_id']}/submit-approval",
            headers={**headers, "Idempotency-Key": "handoff-submit-ui-001"},
        )
        approval = client.get("/api/v1/approvals?limit=20", headers=headers).json()[0]
        approved = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            headers={**headers, "Idempotency-Key": "handoff-approval-ui-001"},
            json={
                "decision": "approve",
                "request_digest": approval["request_digest"],
                "reason": "批准准备完成的受控 Handoff。",
            },
        )
        final = client.get(f"/api/v1/handoffs/{item['handoff_id']}", headers=headers)
        queue_after = client.get("/api/v1/status", headers=headers).json()["task_counts"]

    assert templates.status_code == 200
    assert templates.json() == [
        {
            "template_id": "picotoopet-repo-maintenance-v1",
            "display_name": "PicotooPet 仓库维护",
            "provider": "manual",
            "provider_configured": False,
            "repo_url": "https://github.com/jerryjwres-hue/picotoopet-v2.0",
            "base_ref": "feature/phase23-slice-d-diagnostic-snapshot-release",
            "base_commit": "5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
        }
    ]
    assert prepared.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == item
    assert item["status"] == "prepared"
    assert item["provider"] == "manual"
    assert item["provider_configured"] is False
    assert len(item["request_digest"]) == 64
    assert len(item["package_digest"]) == 64
    assert listed.status_code == 200
    assert listed.json()[0]["handoff_id"] == item["handoff_id"]
    assert fetched.json() == item
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "waiting_approval"
    assert submit_replay.json() == submitted.json()
    assert approval["approval_type"] == "handoff.prepare"
    assert "handoff_id=" in approval["scope_summary"]
    assert "request_digest=" in approval["scope_summary"]
    assert approved.status_code == 200
    assert final.json()["status"] == "approved"
    assert queue_after == queue_before
    assert "token" not in prepared.text.lower()
    assert "token" not in submitted.text.lower()


def test_prepare_and_submit_require_idempotency_keys(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        prepare = client.post(
            "/api/v1/handoffs/prepare",
            headers=headers,
            json=prepare_payload(),
        )
        prepared = client.post(
            "/api/v1/handoffs/prepare",
            headers={**headers, "Idempotency-Key": "handoff-prepare-ui-002"},
            json=prepare_payload(),
        ).json()
        submit = client.post(
            f"/api/v1/handoffs/{prepared['handoff_id']}/submit-approval",
            headers=headers,
        )

    assert prepare.status_code == 422
    assert submit.status_code == 422


def test_prepare_requires_authentication(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        response = client.get("/api/v1/handoffs/templates")
    assert response.status_code == 401
