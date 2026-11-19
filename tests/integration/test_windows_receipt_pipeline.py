import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from requests import Session

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from scripts.windows.executor_bridge import Bridge, BridgeConfig
from scripts.windows.import_video_candidates import BOARD, RUNNER

IMPORTER = Path(__file__).resolve().parents[2] / "scripts/windows/import_video_candidates.py"


@pytest.fixture
def video_batch(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("需要本机 FFmpeg / FFprobe 生成纯色测试素材")
    root = tmp_path / "project"
    board = root / BOARD
    done = root / "_queue" / "done"
    media = root / "stills and clips"
    for directory in (board, done, media):
        directory.mkdir(parents=True)

    def stamp(path, seconds):
        t = time.time_ns() + seconds * 1_000_000_000
        os.utime(path, ns=(t, t))

    def write(path, value, seconds):
        path.write_text(json.dumps(value), encoding="utf-8")
        stamp(path, seconds)

    (media / "first.png").write_bytes(b"placeholder frame")
    jobs = {
        "out": "../stills and clips",
        "jobs": [
            {
                "id": "fixture_S01",
                "seeds": [123],
                "w": 128,
                "h": 72,
                "seconds": 1.0,
                "prompt": "Static color",
                "first": "../stills and clips/first.png",
            }
        ],
    }
    write(board / "jobs.json", jobs, -50)
    write(done / "receipt.json", {"runner": RUNNER, "jobs": "jobs.json"}, -40)
    clip = media / "fixture_S01_v1.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=teal:s=128x72:r=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(clip),
        ],
        check=True,
        timeout=30,
    )
    stamp(clip, -30)
    receipt = done / "receipt.result.json"
    write(
        receipt,
        {
            "task": "receipt",
            "runner": RUNNER,
            "ok": True,
            "returncode": 0,
            "fails": [],
            "outputs": ["stills and clips\\fixture_S01_v1.mp4"],
        },
        -20,
    )
    return root, receipt, clip


def test_completed_video_receipt_offline_review_then_authenticated_idempotent_import(
    tmp_path, video_batch
):
    root, receipt, clip = video_batch
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    base = [
        sys.executable,
        str(IMPORTER),
        "--project-root",
        str(root),
        "--receipt",
        str(receipt),
        "--shot-prefix",
        "fixture_",
        "--episode-id",
        "demo",
    ]

    def run(*arguments):
        completed = subprocess.run(
            [*base, *arguments],
            capture_output=True,
            timeout=30,
            encoding="utf-8",
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    page = tmp_path / "screening.html"
    assert run("--review-page", str(page))["mode"] == "review-page"
    html = page.read_text(encoding="utf-8")
    encoded = re.search(r'<script id="batch" type="application/json">(.*?)</script>', html)
    assert encoded is not None
    (candidate,) = json.loads(encoded[1])["candidates"]
    assert candidate["uri"] == clip.as_uri()
    assert candidate["source_id"] == "receipt:fixture_S01:v1"
    notes = tmp_path / "selection.json"
    notes.write_text(
        json.dumps(
            {
                "version": 1,
                "episode_id": "demo",
                "decisions": [
                    {
                        **{
                            key: candidate[key]
                            for key in ("shot_id", "take", "source_id", "sha256")
                        },
                        "decision": "pick",
                        "note": "first take",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = run("--emit-manifest", "--decisions", str(notes), "--probe", "--thumbnails")
    (item,) = manifest["candidates"]
    assert (item["shot_id"], item["take"], item["seed"]) == ("S01", 1, 123)
    assert item["qc"]["实测"]["尺寸"] == [128, 72]
    assert item["qc"]["实测"]["音轨数"] == 1
    assert item["qc"]["差异"] == []
    assert item["decision"] == "pick"
    assert item["jpeg_base64"]
    assert manifest["fill_unreviewed"] is True
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert not (root / "_queue" / "inbox").exists()

    if os.name != "nt":
        # The Core receives Windows paths regardless of the OS hosting the API.
        item["path"] = r"C:\screening\fixture_S01_v1.mp4"
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path / "core"), api_token=token))
    endpoint = "/api/v1/episodes/import"
    with TestClient(app) as client:
        assert client.post(endpoint, json=manifest).status_code == 401
        auth = {"Authorization": f"Bearer {token}"}
        registration = {
            **manifest,
            "fill_unreviewed": False,
            "candidates": [
                {key: value for key, value in item.items() if key not in {"decision", "note"}}
            ],
        }
        response = client.post(endpoint, headers=auth, json=registration)
        assert response.status_code == 201, response.text
        assert response.json() == {"episode_id": "demo", "inserted_count": 1, "existing_count": 0}
        response = client.post(endpoint, headers=auth, json=manifest)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "episode_id": "demo",
            "inserted_count": 0,
            "existing_count": 1,
            "updated_count": 1,
        }
        response = client.post(endpoint, headers=auth, json=manifest)
        assert response.status_code == 200, response.text
        assert response.json() == {"episode_id": "demo", "inserted_count": 0, "existing_count": 1}

        review = client.get("/api/v1/episodes/demo/review", headers=auth).json()
        (imported,) = review["shots"][0]["candidates"]
        assert (imported["decision"], imported["note"]) == ("pick", "first take")
        assert (imported["seed"], imported["source_id"]) == (123, candidate["source_id"])
        lease = {"worker_id": "test", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
        assert client.post("/api/v1/executors/lease", headers=auth, json=lease).status_code == 204


@pytest.mark.skipif(os.name != "nt" or not shutil.which("dotnet"), reason="需要 Windows WPF SDK")
def test_wpf_asks_live_core_to_assemble_selected_local_video(video_batch, live_core):
    root, receipt, _ = video_batch
    url, headers = live_core
    project = IMPORTER.parents[2] / "windows/desktop"
    env = {
        **os.environ,
        "PICOTOO_TEST_CORE_URL": url,
        "PICOTOO_TEST_CORE_TOKEN": headers["Authorization"].removeprefix("Bearer "),
        "PICOTOO_TEST_RECEIPT": str(receipt),
        "PYTHONUTF8": "1",
    }
    result = subprocess.run(
        [
            "dotnet",
            "run",
            "--project",
            "tests/PicotooPet.Desktop.Production.SmokeTests",
            "--",
            "--live-core",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        timeout=150,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    with Session() as session:
        session.trust_env = False
        session.headers.update(headers)
        tasks = session.get(url + "/api/v1/tasks", timeout=5).json()
        assert sorted(t["task_type"] for t in tasks) == ["edit.assemble", "review.imported"]
        assembly = next(t for t in tasks if t["task_type"] == "edit.assemble")
        bridge = Bridge(BridgeConfig(url, "desktop-test", root), session)
        for _ in range(3):
            bridge.step()
            task = session.get(url + "/api/v1/tasks/" + assembly["task_id"], timeout=5).json()
            if task["status"] == "Completed":
                break
        assert task["status"] == "Completed", task
        artifacts = session.get(
            url + f"/api/v1/tasks/{assembly['task_id']}/artifacts",
            timeout=5,
        ).json()["artifacts"]
        assert any(a["kind"] == "video" and Path(a["path"]).stat().st_size > 0 for a in artifacts)
