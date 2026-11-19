import hashlib
from pathlib import Path

import pytest
import requests
from PIL import Image

from scripts.windows.executor_bridge import Bridge, BridgeConfig, JobError


def test_local_qc_images_reports_per_digest_and_rejects_replaced_media(tmp_path):
    with requests.Session() as session:
        bridge = Bridge(BridgeConfig("http://localhost", "review", tmp_path), session)
        bridge.next_heartbeat = float("inf")
        candidates = []
        for index, colour in enumerate(["blue", "red"], 1):
            img = tmp_path / f"样片{index}.png"
            Image.new("RGB", (96, 64), colour).save(img)
            candidates.append(
                {
                    "kind": "image",
                    "path": str(img),
                    "sha256": hashlib.sha256(img.read_bytes()).hexdigest(),
                }
            )
        state = {
            "stem": "review_1",
            "task": {
                "task_type": "qc.check",
                "timeout_seconds": 60,
                "payload": {
                    "runner": "qc.check",
                    "shot_id": "S01",
                    "jobs": {
                        "source_jobs": {"qc_spec": {"expect": {"dogs": 1}}},
                        "artifacts": candidates,
                    },
                },
            },
        }
        result = bridge._work(state)
        assert result["qc"]["passed"] is False
        assert result["qc"]["fails"]
        for candidate in candidates:
            item = result["qc"]["by_sha256"][candidate["sha256"]]
            assert item["report"]["shot_id"] == "S01"
            assert item["report"]["pass"] is item["passed"]
            assert any(f["check"] == "dog_count" for f in item["report"]["fails"])
        bridge._stage_report(state, result)
        assert {p["digest"] for p in state["previews"]} == {
            None,
            *(c["sha256"] for c in candidates),
        }
        assert all(Path(p["path"]).read_bytes().startswith(b"\xff\xd8") for p in state["previews"])
        candidates[0]["sha256"] = "0" * 64
        with pytest.raises(JobError, match="哈希"):
            bridge._work(state)


def test_foley_digest_maps_to_the_selected_source_even_when_takes_are_reordered(tmp_path):
    with requests.Session() as session:
        bridge = Bridge(BridgeConfig("http://localhost", "review", tmp_path), session)
        bridge.next_heartbeat = float("inf")
        candidates = [
            {
                "path": str(tmp_path / f"clip{i}.mp4"),
                "kind": "video",
                "sha256": str(i) * 64,
                "decision": "pick" if i == 2 else None,
                "take": i,
            }
            for i in (1, 2)
        ]
        bridge._parent = lambda task: candidates
        state = {
            "stem": "mix",
            "task": {
                "task_type": "gen.foley",
                "payload": {
                    "shot_id": "S01",
                    "jobs": {
                        "out": "$bridge.output",
                        "jobs": [{"id": "sound", "video": "$parent.video", "seeds": [1]}],
                    },
                },
            },
        }
        jobs = bridge._jobs(state)
        tracks = []
        for i, job in enumerate(jobs["jobs"]):
            audio = tmp_path / (job["id"] + "_v1.wav")
            audio.write_bytes(bytes([i]))
            tracks.append(audio)
        bridge._stage_report(state, {"ok": True, "outputs": [str(p) for p in tracks]})
        links = state["report"]["qc"]["foley_by_sha256"]
        for job, audio in zip(jobs["jobs"], tracks, strict=True):
            source = next(c for c in candidates if c["path"] == job["video"])
            assert links[hashlib.sha256(audio.read_bytes()).hexdigest()] == source["sha256"]
