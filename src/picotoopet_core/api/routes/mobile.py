"""HTTPS-only read-only mobile Studio on the existing Mac Core process."""

from __future__ import annotations

import base64
import html
import re
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from picotoopet_core.domain.storypack import (
    StoryPackError,
    parse_storypack,
    storypack_preview,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter()
_COOKIE = "__Host-picotoo-mobile"
_MAX_BODY = 160 * 1024
_REVIEW_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


def _page(contents: str, *, status_code: int = 200) -> HTMLResponse:
    # 没有 JS、远端资源或前端设备 Token；动态数据只由服务器 HTML 转义。
    source = """<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Picotoo Studio</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif}
body{background:#111827;color:#f9fafb;margin:0;line-height:1.45}
main{max-width:680px;margin:auto;padding:16px 14px 45px}
h1{font-size:23px;margin:14px 0 6px}h2{font-size:17px;margin:0 0 9px}
small,.muted{color:#9ca3af}.card{background:#1f2937;border:1px solid #374151;
border-radius:13px;padding:14px;margin:12px 0}
a{color:#93c5fd}button{background:#2563eb;color:white;border:0;border-radius:9px;
font-size:16px;font-weight:600;padding:12px 18px;cursor:pointer}
input,textarea{box-sizing:border-box;background:#111827;color:white;border:1px solid #6b7280;
border-radius:9px;padding:12px;width:100%;font-size:16px;margin:9px 0}
textarea{min-height:180px;font-family:ui-monospace,monospace}
.preview{display:block;max-width:100%;max-height:300px;border-radius:9px;margin-top:8px}
.tag{font-size:12px;padding:3px 8px;border-radius:20px;background:#374151}
.entry{padding:8px 0;border-bottom:1px solid #374151;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
nav{display:flex;gap:16px}strong{overflow-wrap:anywhere}
</style></head><body><main>"""
    return HTMLResponse(
        source + contents + "</main></body></html>",
        status_code=status_code,
        headers=_HEADERS,
    )


def _enabled(request: Request) -> bool:
    return bool(request.app.state.services.settings.mobile_studio_enabled)


def _encrypted(request: Request) -> bool:
    # 只信 ASGI 可信代理设置的 scheme；不相信客户端伪造的 X-Forwarded-Proto。
    return request.url.scheme == "https"


def _session(request: Request) -> bool:
    return request.app.state.mobile_access.valid(request.cookies.get(_COOKIE))


def _login_page(message: str = "") -> HTMLResponse:
    warning = "<p class='muted'>" + html.escape(message) + "</p>" if message else ""
    return _page(
        "<h1>Picotoo Studio</h1><p class='muted'>手机只读控制台 · 不启动 GPU</p>"
        "<section class='card'><h2>手机首次配对</h2>"
        "<p>请在已连接 Mac Core 的 Windows 控制台取得一次性配对码。</p>"
        + warning
        + "<form method='post' action='/mobile/login'>"
        "<label for='code'>一次性配对码</label>"
        "<input id='code' name='code' inputmode='text' autocomplete='one-time-code'"
        " maxlength='12' required><button type='submit'>登录</button></form>"
        "</section>"
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


async def _form(request: Request) -> dict[str, str]:
    typ = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if typ != "application/x-www-form-urlencoded":
        raise ValueError("FORM_REQUIRED")
    # 浏览器 POST 需要相同的 Origin；拒绝跨站提交携带的会话 Cookie。
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise ValueError("ORIGIN_MISMATCH")
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > _MAX_BODY:
            raise ValueError("FORM_TOO_LARGE")
        body.extend(part)
    try:
        fields = parse_qs(body.decode("utf-8"), max_num_fields=3)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("FORM_INVALID") from exc
    return {key: values[0] for key, values in fields.items() if values}


@router.post("/api/v1/mobile/pairing", dependencies=[Depends(require_auth)])
def create_mobile_pairing(request: Request) -> dict:
    """Only a paired device can display a one-time phone pairing code."""
    if not _enabled(request):
        return {"enabled": False, "code": None, "read_only": True}
    return request.app.state.mobile_access.issue_pairing()


@router.get("/mobile")
def mobile_dashboard(request: Request) -> HTMLResponse:
    if not _enabled(request):
        return _page("<h1>手机控制台未启用</h1>", status_code=404)
    if not _encrypted(request):
        return _page("<h1>请通过 HTTPS 私有入口访问</h1>", status_code=403)
    if not _session(request):
        return _login_page()

    db = request.app.state.services.database
    states = db.fetchall(
        "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status"
    )
    tasks = db.fetchall(
        "SELECT task_type, status, task_id FROM tasks ORDER BY rowid DESC LIMIT 12"
    )
    episodes = db.fetchall(
        "SELECT episode_id, json_extract(spec_json, '$.title') AS title "
        "FROM production_episodes ORDER BY rowid DESC LIMIT 12"
    )
    status_lines = "".join(
        "<span class='tag'>" + _escape(row["status"]) + ": " + str(row["n"])
        + "</span> " for row in states
    ) or "<span class='muted'>暂无任务</span>"
    task_lines = "".join(
        "<div class='entry'><strong>" + _escape(row["task_type"]) + "</strong> · "
        + _escape(row["status"]) + "<br><small>" + _escape(row["task_id"]) + "</small></div>"
        for row in tasks
    ) or "<p class='muted'>暂无任务</p>"
    episode_lines = "".join(
        "<div class='entry'><a href='/mobile/episodes/"
        + quote(str(row["episode_id"]), safe="") + "'>"
        + _escape(row["title"] or row["episode_id"]) + "</a>"
        + "<br><small>" + _escape(row["episode_id"]) + "</small></div>"
        for row in episodes
    ) or "<p class='muted'>暂无剧集</p>"
    return _page(
        "<nav><strong>Picotoo Studio</strong><a href='/mobile'>刷新状态</a>"
        "<a href='/mobile/logout'>退出</a></nav>"
        "<p class='muted'>仅查看与预览 · GPU HOLD 不变</p>"
        "<section class='card'><h2>生产状态</h2>" + status_lines + "</section>"
        "<section class='card'><h2>最新任务</h2>" + task_lines + "</section>"
        "<section class='card'><h2>剧集</h2>" + episode_lines + "</section>"
        "<section class='card'><h2>验证 StoryPack</h2>"
        "<p class='muted'>粘贴 JSON，查看镜头规格；不会创建任务。</p>"
        "<form method='post' action='/mobile/preview'>"
        "<textarea name='storypack' maxlength='131072' required></textarea>"
        "<button type='submit'>只读预览</button></form></section>"
    )


@router.post("/mobile/login")
async def mobile_login(request: Request):
    if not _enabled(request):
        return _page("未启用", status_code=404)
    if not _encrypted(request):
        return _page("HTTPS_REQUIRED", status_code=403)
    try:
        form = await _form(request)
    except ValueError:
        return _login_page("请求格式或来源无效。")
    source = request.client.host if request.client else "unknown"
    secret = request.app.state.mobile_access.claim(form.get("code", ""), source)
    if secret is None:
        return _login_page("配对码无效或已过期。")
    response = RedirectResponse("/mobile", status_code=303, headers=_HEADERS)
    response.set_cookie(
        _COOKIE, secret, max_age=8 * 3600, secure=True, httponly=True,
        samesite="strict", path="/",
    )
    return response


@router.get("/mobile/logout")
def mobile_logout(request: Request):
    request.app.state.mobile_access.revoke(request.cookies.get(_COOKIE))
    response = RedirectResponse("/mobile", status_code=303, headers=_HEADERS)
    response.delete_cookie(_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.post("/mobile/preview")
async def mobile_preview(request: Request):
    if not _enabled(request) or not _encrypted(request):
        return _page("NOT_AVAILABLE", status_code=403)
    if not _session(request):
        return _login_page("会话过期，请重新配对。")
    try:
        fields = await _form(request)
        source = fields.get("storypack", "")
        if len(source.encode("utf-8")) > 128 * 1024:
            raise ValueError("STORYPACK_TOO_LARGE")
        pack = parse_storypack(source.encode("utf-8"), as_yaml=False)
        preview = storypack_preview(pack)
    except (ValueError, StoryPackError):
        return _page(
            "<h1>故事包格式不正确</h1><p>请检查 JSON 内容。</p>"
            "<p><a href='/mobile'>返回创作台</a></p>", status_code=422
        )
    output = preview["output"]
    shots = "".join(
        "<div class='entry'>" + _escape(s["id"]) + " · " + _escape(s["action"])
        + "</div>" for s in preview["shots"]
    )
    return _page(
        "<nav><a href='/mobile'>返回创作台</a></nav>"
        "<h1>StoryPack 预览</h1><section class='card'>"
        "<p><strong>" + _escape(preview["episode_id"]) + "</strong></p>"
        "<p>" + str(preview["shot_count"]) + " 镜 · "
        + str(output["planned_duration_s"]) + " 秒 · "
        + str(output["width"]) + "×" + str(output["height"]) + "</p>"
        "<small>状态：仅预览，不可自动生成</small>"
        + shots + "</section>"
    )


@router.get("/mobile/episodes/{episode_id}")
def mobile_episode_review(episode_id: str, request: Request):
    """Read-only shot candidate cards; never expose decision endpoints to mobile."""
    if not _enabled(request) or not _encrypted(request):
        return _page("NOT_AVAILABLE", status_code=403)
    if not _session(request):
        return _login_page("会话过期，请重新配对。")
    if _REVIEW_ID.fullmatch(episode_id) is None:
        return _page("剧集编号无效", status_code=404)
    try:
        review = request.app.state.services.production.review(episode_id)
    except KeyError:
        return _page("剧集不存在", status_code=404)

    cards = []
    for shot in review.shots[:30]:
        candidates = []
        for item in shot.candidates[:6]:
            # 仅显示人工审核有用的字段，不把内部媒体路径或完整 manifest 暴露到手机。
            qc = item.qc if isinstance(item.qc, dict) else {}
            quality = qc.get("gate_status") or qc.get("status") or "待复查"
            decision = item.decision or "未选择"
            caption = (
                "<div class='entry'><span class='tag'>" + _escape(item.kind)
                + "</span> <span class='tag'>QC：" + _escape(quality)
                + "</span> <span class='tag'>选择：" + _escape(decision) + "</span>"
            )
            thumb = item.thumbnail_id or item.sheet_thumbnail_id
            if thumb and _REVIEW_ID.fullmatch(item.task_id) and _REVIEW_ID.fullmatch(thumb):
                path = (
                    "/mobile/thumb/" + quote(item.task_id, safe="")
                    + "/" + quote(thumb, safe="")
                )
                caption += "<img class='preview' loading='lazy' alt='镜头预览' src='" + path + "'>"
            caption += "</div>"
            candidates.append(caption)
        cards.append(
            "<section class='card'><h2>" + _escape(shot.shot_id)
            + " · " + _escape(shot.status) + "</h2>"
            + "".join(candidates or ["<p class='muted'>暂无候选素材</p>"])
            + "</section>"
        )

    return _page(
        "<nav><a href='/mobile'>返回控制台</a></nav>"
        "<h1>剧集审阅 · " + _escape(episode_id) + "</h1>"
        "<p class='muted'>只读候选画廊，不包含选片或重新生成授权。</p>"
        "<section class='card'><strong>合成条件：</strong>"
        + ("已满足现有 QC 门禁" if review.can_assemble else "尚未满足") + "</section>"
        + "".join(cards or ["<p class='muted'>暂无分镜</p>"])
    )


@router.get("/mobile/thumb/{task_id}/{thumbnail_id}")
def mobile_thumbnail(task_id: str, thumbnail_id: str, request: Request):
    """Proxy only recorded JPEG thumbnails behind a valid mobile session."""
    if not _enabled(request) or not _encrypted(request) or not _session(request):
        return Response(status_code=404, headers=_HEADERS)
    if _REVIEW_ID.fullmatch(task_id) is None or _REVIEW_ID.fullmatch(thumbnail_id) is None:
        return Response(status_code=404, headers=_HEADERS)
    try:
        content = request.app.state.services.executor.thumbnail(task_id, thumbnail_id)
        jpeg = base64.b64decode(content.jpeg_base64, validate=True)
    except (KeyError, ValueError, base64.binascii.Error):
        return Response(status_code=404, headers=_HEADERS)
    if len(jpeg) > 300 * 1024 or not jpeg.startswith(b"\xff\xd8"):
        return Response(status_code=404, headers=_HEADERS)
    return Response(jpeg, media_type="image/jpeg", headers=_HEADERS)
