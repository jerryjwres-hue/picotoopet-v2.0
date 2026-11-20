"""Mobile gallery proxies approved stored thumbnails without expanding permissions."""

import base64
import secrets
from types import SimpleNamespace

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _paired_client(tmp_path):
    token = secrets.token_urlsafe(32)
    app = create_app(
        AppSettings(
            paths=RuntimePaths.from_root(tmp_path),
            api_token=token,
            mobile_studio_enabled=True,
        )
    )
    return app, token


def _login(phone, token):
    r = phone.post(
        "/api/v1/mobile/pairing", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    c = phone.post(
        "/mobile/login",
        data={"code": r.json()["code"]},
        headers={"Origin": "https://studio.example"},
        follow_redirects=False,
    )
    assert c.status_code == 303


def test_gallery_is_scoped_readonly_and_escaped(tmp_path):
    app, token = _paired_client(tmp_path)
    image = b"\xff\xd8\xff\xd9"
    candidate = SimpleNamespace(
        kind="video", decision=None, thumbnail_id="thumb1", sheet_thumbnail_id=None,
        task_id="task1", qc={"gate_status": "<script>invalid</script>"},
    )
    shot = SimpleNamespace(
        shot_id="S01", status="QC_MANUAL_REVIEW", candidates=[candidate],
    )
    review = SimpleNamespace(shots=[shot], can_assemble=False)
    app.state.services.production.review = lambda episode_id: review
    app.state.services.executor.thumbnail = lambda task_id, thumbnail_id: SimpleNamespace(
        jpeg_base64=base64.b64encode(image).decode("ascii")
    )
    with TestClient(app, base_url="https://studio.example") as phone:
        before = phone.get("/mobile/episodes/demo")
        assert before.status_code == 200
        assert "手机首次配对" in before.text
        assert "S01" not in before.text
        assert phone.get("/mobile/thumb/task1/thumb1").status_code == 404
        _login(phone, token)
        page = phone.get("/mobile/episodes/demo")
        assert page.status_code == 200
        assert "S01" in page.text
        assert "QC_MANUAL_REVIEW" in page.text
        assert "&lt;script&gt;invalid&lt;/script&gt;" in page.text
        assert "<script>invalid</script>" not in page.text
        assert "/mobile/thumb/task1/thumb1" in page.text
        assert "img-src 'self'" in page.headers["content-security-policy"]
        thumbnail = phone.get("/mobile/thumb/task1/thumb1")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"].startswith("image/jpeg")
        assert thumbnail.content == image
        # 手机会话不取得设备令牌，也不能直接调用原有生产决策 REST 接口。
        denied = phone.post("/api/v1/episodes/demo/assemble")
        assert denied.status_code == 401
        assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_thumbnail_missing_or_invalid_is_not_served(tmp_path):
    app, token = _paired_client(tmp_path)
    app.state.services.executor.thumbnail = lambda task_id, thumbnail_id: SimpleNamespace(
        jpeg_base64=base64.b64encode(b"<script>").decode("ascii")
    )
    with TestClient(app, base_url="https://studio.example") as phone:
        _login(phone, token)
        assert phone.get("/mobile/thumb/task1/thumb1").status_code == 404
        assert phone.get("/mobile/thumb/invalid%24/thumb1").status_code == 404
        assert phone.get("/mobile/episodes/invalid%24").status_code == 404


def test_gallery_does_not_return_data_to_insecure_http(tmp_path):
    app, token = _paired_client(tmp_path)
    with TestClient(app, base_url="http://studio.example") as phone:
        assert phone.get("/mobile/episodes/demo").status_code == 403
        assert phone.get("/mobile/thumb/task1/thumb1").status_code == 404
