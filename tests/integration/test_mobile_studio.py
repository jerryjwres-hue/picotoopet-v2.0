"""Mobile Studio pairing/status are HTTPS-only and cannot enqueue GPU tasks."""

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


@pytest.fixture
def fixture(tmp_path):
    token = secrets.token_urlsafe(32)
    app = create_app(
        AppSettings(
            paths=RuntimePaths.from_root(tmp_path),
            api_token=token,
            mobile_studio_enabled=True,
        )
    )
    with TestClient(app, base_url="https://studio.example") as phone:
        yield phone, app, token


def _pair(phone, token):
    response = phone.post(
        "/api/v1/mobile/pairing",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["enabled"] is True
    return response.json()["code"]


def _login(phone, code):
    return phone.post(
        "/mobile/login",
        data={"code": code},
        headers={"Origin": "https://studio.example"},
        follow_redirects=False,
    )


def _storypack():
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "E02",
        "title": "Maotai dinner",
        "character_ref": "maotai_master_v1",
        "scene_ref": "kitchen_v1",
        "story": {"goal": "Reach dinner", "payoff": "See the prepared food"},
        "shots": [
            {
                "id": "S01", "action": "Walk to the table",
                "state_in": "At doorway", "state_out": "By table",
                "because": "Smells dinner",
            }
        ],
    }


def test_disabled_by_default_and_device_auth_required(tmp_path):
    token = secrets.token_urlsafe(32)
    app = create_app(
        AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token)
    )
    with TestClient(app, base_url="https://studio.example") as client:
        assert client.get("/mobile").status_code == 404
        denied = client.post("/api/v1/mobile/pairing")
        assert denied.status_code == 401
        disabled = client.post(
            "/api/v1/mobile/pairing",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert disabled.json() == {"enabled": False, "code": None, "read_only": True}
        assert client.get("/mobile").status_code == 404


def test_pairing_creates_secure_readonly_mobile_session(fixture):
    phone, app, token = fixture
    public = phone.get("/mobile")
    assert "手机首次配对" in public.text
    assert "最新任务" not in public.text
    assert token not in public.text

    code = _pair(phone, token)
    response = _login(phone, code)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "__Host-picotoo-mobile=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie

    dashboard = phone.get("/mobile")
    assert dashboard.status_code == 200
    assert "生产状态" in dashboard.text
    assert "验证 StoryPack" in dashboard.text
    assert token not in dashboard.text
    assert code not in dashboard.text
    assert dashboard.headers["cache-control"].startswith("no-store")
    assert dashboard.headers["content-security-policy"].startswith("default-src 'none'")
    assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_pairing_is_one_time_and_wrong_codes_rate_limited(fixture):
    phone, app, token = fixture
    code = _pair(phone, token)
    for _ in range(5):
        assert _login(phone, "BADCODE").status_code == 200
    assert _login(phone, code).status_code == 200
    # 新配对码的签发清空当前错误尝试，随后一个码只能被消费一次。
    code = _pair(phone, token)
    assert _login(phone, code).status_code == 303
    assert _login(phone, code).status_code == 200


def test_invalid_origin_is_rejected_even_with_valid_code(fixture):
    phone, _, token = fixture
    code = _pair(phone, token)
    bad = phone.post(
        "/mobile/login",
        data={"code": code},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert bad.status_code == 200
    assert "请求格式或来源无效" in bad.text
    assert _login(phone, code).status_code == 303


def test_http_phone_login_is_blocked_even_with_valid_pairing(tmp_path):
    token = secrets.token_urlsafe(32)
    app = create_app(
        AppSettings(
            paths=RuntimePaths.from_root(tmp_path),
            api_token=token,
            mobile_studio_enabled=True,
        )
    )
    with TestClient(app, base_url="http://192.168.1.20") as phone:
        code = _pair(phone, token)
        assert phone.get("/mobile").status_code == 403
        insecure = phone.post(
            "/mobile/login",
            data={"code": code},
            headers={"Origin": "http://192.168.1.20"},
        )
        assert insecure.status_code == 403
        assert "__Host-picotoo-mobile" not in insecure.headers.get("set-cookie", "")


def test_storypack_preview_readonly_and_html_escaped(fixture):
    phone, app, token = fixture
    code = _pair(phone, token)
    assert _login(phone, code).status_code == 303
    preview = phone.post(
        "/mobile/preview",
        data={"storypack": json.dumps(_storypack())},
        headers={"Origin": "https://studio.example"},
    )
    assert preview.status_code == 200
    assert "E02" in preview.text
    assert "1 镜" in preview.text
    assert "不可自动生成" in preview.text
    assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0

    attack = _storypack()
    attack["shots"][0]["action"] = "<script>alert(1)</script>"
    safe = phone.post(
        "/mobile/preview",
        data={"storypack": json.dumps(attack)},
        headers={"Origin": "https://studio.example"},
    )
    assert safe.status_code == 200
    assert "<script>alert(1)</script>" not in safe.text
    assert "&lt;script&gt;" in safe.text
    assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_storypack_preview_requires_session_and_same_origin(fixture):
    phone, app, token = fixture
    hidden = phone.post(
        "/mobile/preview",
        data={"storypack": json.dumps(_storypack())},
        headers={"Origin": "https://studio.example"},
    )
    assert "手机首次配对" in hidden.text
    assert "E02" not in hidden.text

    code = _pair(phone, token)
    assert _login(phone, code).status_code == 303
    blocked = phone.post(
        "/mobile/preview",
        data={"storypack": json.dumps(_storypack())},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 422
    assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_logout_revokes_browser_session(fixture):
    phone, _, token = fixture
    code = _pair(phone, token)
    assert _login(phone, code).status_code == 303
    assert "最新任务" in phone.get("/mobile").text
    response = phone.get("/mobile/logout", follow_redirects=False)
    assert response.status_code == 303
    assert "最新任务" not in phone.get("/mobile").text
