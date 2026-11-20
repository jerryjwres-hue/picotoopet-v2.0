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


def test_best_candidate_is_advisory_and_ignores_bad_or_old_qc(tmp_path):
    from picotoopet_core.api.routes.mobile import _suggest_verified_take

    def candidate(artifact_id, score, *, passed=True, superseded=False,
                  gate="Completed", decision=None, take=1):
        return SimpleNamespace(
            artifact_id=artifact_id, kind="video", decision=decision, take=take,
            task_id="task1", thumbnail_id=None, sheet_thumbnail_id=None,
            sha256=artifact_id * 64,
            qc={
                "score": score, "passed": passed, "gate_status": gate,
                "superseded": superseded, "report_task_id": "qc-current",
            },
        )

    selection = [
        candidate("a", 70, take=1),
        candidate("b", 94, take=2),
        candidate("c", 99, passed=False),
        candidate("d", 100, superseded=True),
        candidate("e", 99, gate="QC_MANUAL_REVIEW"),
        candidate("f", 98, decision="reject"),
    ]
    assert _suggest_verified_take(selection) == "b"
    assert _suggest_verified_take(selection[::-1]) == "b"
    assert _suggest_verified_take([selection[2], selection[3], selection[4]]) is None
    assert _suggest_verified_take([
        candidate("j", 90, take=3),
        candidate("i", 90, take=1),
    ]) == "i"
    # 输出建议 ID 并非数据库选片；移动端会话仍不具备写入生产任务的权限。
    app, token = _paired_client(tmp_path)
    shot = SimpleNamespace(shot_id="S01", status="待审片", candidates=selection)
    app.state.services.production.review = lambda episode_id: SimpleNamespace(
        shots=[shot], can_assemble=False
    )
    with TestClient(app, base_url="https://studio.example") as phone:
        _login(phone, token)
        page = phone.get("/mobile/episodes/demo")
        assert page.status_code == 200
        assert page.text.count("推荐候选（仅建议，不自动选用）") == 1
        assert app.state.services.database.scalar(
            "SELECT COUNT(*) FROM executor_artifacts WHERE decision='pick'"
        ) == 0
        assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_unverified_or_invalid_scores_are_not_recommended():
    from picotoopet_core.api.routes.mobile import _suggest_verified_take

    def item(score):
        return SimpleNamespace(
            artifact_id="clip1", kind="video", decision=None, take=1, sha256="a" * 64,
            qc={"score": score, "passed": True, "gate_status": "Completed",
                "superseded": False, "report_task_id": "qc1"},
        )

    assert _suggest_verified_take([item(True)]) is None
    assert _suggest_verified_take([item(float("nan"))]) is None
    assert _suggest_verified_take([item(float("inf"))]) is None
    assert _suggest_verified_take([item(-1)]) is None
    assert _suggest_verified_take([item(101)]) is None
