"""Exercise the offline board with two local solid-color movies in a disposable Edge profile."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from scripts.windows.review_board import apply_decisions, write_review_page


def test_offline_playback_and_export_roundtrip(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"
    if not edge.is_file() or not shutil.which("ffmpeg"):
        pytest.skip("此浏览器验收需要 Windows Edge 和 FFmpeg")
    candidates = []
    for take, color in enumerate(("red", "blue"), 1):
        video = tmp_path / f"本地候选 #{take}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:size=96x64:rate=24",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t",
                str(take + 1),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(video),
            ],
            check=True,
            timeout=30,
        )
        candidates.append(
            {
                "shot_id": "S01",
                "take": take,
                "seed": 9 + take,
                "source_id": "fake",
                "kind": "video",
                "path": str(video),
                "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "episode": {
            "episode_id": "demo",
            "title": "同步播放测试",
            "edit": {"fps": 24},
            "shots": [{"shot_id": "S01"}],
        },
        "candidates": candidates,
    }
    board = tmp_path / "review.html"
    write_review_page(manifest, board)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=edge, headless=True)
        page = browser.new_page()
        errors = []
        remote = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request", lambda req: remote.append(req.url) if req.url.startswith("http") else None
        )
        page.goto(board.as_uri())

        def wait_until(predicate):
            until = time.monotonic() + 10
            while not page.evaluate(predicate):
                if time.monotonic() >= until:
                    pytest.fail(f"播放器状态未就绪：{predicate}")
                time.sleep(0.02)

        wait_until("[...document.querySelectorAll('video')].every(v => v.readyState >= 1)")
        assert float(page.get_by_role("slider", name="播放位置").get_attribute("max")) >= 2.9
        page.get_by_role("button", name="同步播放").click()
        wait_until("[...document.querySelectorAll('video')].every(v => v.currentTime > 0.15)")
        page.get_by_role("button", name="暂停").click()
        page.get_by_role("slider", name="播放位置").press("Home")
        page.get_by_role("button", name="下一帧").click()
        wait_until("Math.abs(document.querySelector('video').currentTime - 1/24) < 0.005")
        page.get_by_role("combobox", name="监听").select_option("1")
        assert page.locator("video").evaluate_all("vs => vs.map(v => v.muted)") == [True, False]
        page.get_by_role("button", name="选用", exact=True).first.click()
        page.get_by_role("button", name="选用", exact=True).last.click()
        page.get_by_role("textbox", name="审片备注").last.fill("第二条接触更清晰")
        page.get_by_role("button", name="记下时间点").last.click()
        marked_note = page.get_by_role("textbox", name="审片备注").last.input_value()
        assert "接触更清晰" in marked_note and "秒" in marked_note
        # 新回执加入同一项目后，之前两个候选的离线决定和时间码继续可见。
        manifest["candidates"].append({**candidates[0], "take": 3, "source_id": "retake"})
        write_review_page(manifest, board)
        page.reload()
        assert page.get_by_label("左侧候选").locator("option").nth(1).is_disabled()
        assert page.get_by_role("textbox", name="审片备注").last.input_value() == marked_note
        assert (
            page.get_by_role("button", name="选用", exact=True).first.get_attribute("aria-pressed")
            == "false"
        )
        assert (
            page.get_by_role("button", name="选用", exact=True).last.get_attribute("aria-pressed")
            == "true"
        )
        with page.expect_download() as download:
            page.get_by_role("button", name="导出审片记录").click()
        exported = tmp_path / "export.json"
        download.value.save_as(exported)
        candidates[1].update(decision="reject", note="从另一台审片机明确载入")
        write_review_page(manifest, board)
        page.reload()
        note = page.get_by_role("textbox", name="审片备注").last
        assert note.input_value() == "从另一台审片机明确载入"
        note.fill("载入后再编辑")
        page.reload()
        assert note.input_value() == "载入后再编辑"
        assert not errors
        assert not remote
        browser.close()
    assert len(json.loads(exported.read_text(encoding="utf-8"))["decisions"]) == 1
    apply_decisions(manifest, exported)
    assert (candidates[1]["decision"], candidates[1]["note"]) == ("pick", marked_note)
