import hashlib
import json
import os
import time
from pathlib import Path

import pytest
import requests

from scripts.windows import import_video_candidates as importer


@pytest.fixture
def done_batch(tmp_path):
    board = tmp_path / importer.BOARD
    done = tmp_path / "_queue" / "done"
    media = tmp_path / "clips"
    for folder in board, done, media:
        folder.mkdir(parents=True)
    source = board / "jobs.json"
    request = done / "job.json"
    receipt = done / "job.result.json"

    def write(path, obj, seconds):
        path.write_text(json.dumps(obj), encoding="utf-8")
        stamp = time.time_ns() + seconds * 1_000_000_000
        os.utime(path, ns=(stamp, stamp))

    (media / "first.png").write_bytes(b"fake")
    (media / "last.png").write_bytes(b"fake")
    write(
        source,
        {
            "out": "../clips",
            "jobs": [
                {
                    "id": "cut_S01",
                    "seconds": 3.5,
                    "first": "../clips/first.png",
                    "last": "../clips/last.png",
                    "prompt": "A ball rolls.",
                    "seeds": [42, 12],
                    "w": 544,
                    "h": 960,
                }
            ],
        },
        -50,
    )
    write(request, {"runner": importer.RUNNER, "jobs": source.name}, -40)
    videos = [media / f"cut_S01_v{take}.mp4" for take in (1, 2)]
    for take, video in enumerate(videos, 1):
        video.write_bytes(f"fake take {take}".encode("ascii"))
        stamp = time.time_ns() - 30_000_000_000
        os.utime(video, ns=(stamp, stamp))
    completed = {
        "task": "job",
        "runner": importer.RUNNER,
        "ok": True,
        "returncode": 0,
        "fails": [],
        # The receipt may arrive out of order and always uses Windows paths.
        "outputs": [f"clips\\{video.name}" for video in reversed(videos)],
    }
    write(receipt, completed, -20)
    args = [
        "--project-root",
        str(tmp_path),
        "--jobs",
        source.name,
        "--receipt",
        receipt.name,
        "--shot-prefix",
        "cut_",
        "--episode-id",
        "demo",
    ]
    return args, write, request, receipt, completed, videos


def test_existing_video_batch_maps_take_by_filename_and_seed_order(done_batch, capsys, monkeypatch):
    args, _, _, _, _, videos = done_batch
    monkeypatch.setattr(importer, "_apply", lambda *_: pytest.fail("unexpected network"))
    assert importer.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "dry-run"
    assert [(item["shot_id"], item["take"], item["seed"]) for item in result["candidates"]] == [
        ("S01", 1, 42),
        ("S01", 2, 12),
    ]
    for video, candidate in zip(videos, result["candidates"], strict=True):
        assert Path(candidate["path"]) == video
        assert candidate["sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()


def test_emit_manifest_has_review_only_metadata_without_synthesizing_drama(done_batch, capsys):
    args, *_ = done_batch
    assert importer.main([*args, "--emit-manifest", "--edit-size", "1080", "1920"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["episode_metadata_complete"] is False
    assert manifest["episode"]["target_seconds"] == 3.5
    assert manifest["episode"]["edit"]["size"] == [1080, 1920]
    (shot,) = manifest["episode"]["shots"]
    assert shot["beat"] == shot["emotion"] == "未录入"
    assert shot["video"]["prompt"] == "A ball rolls."
    assert shot["last_frame"]["refs"] == [str(Path("clips/last.png"))]
    assert all("decision" not in item for item in manifest["candidates"])


@pytest.mark.parametrize(
    "damage", ["missing", "early", "modified", "failed", "unfinished", "escape"]
)
def test_incomplete_or_mismatched_studio_batch_is_never_imported(done_batch, capsys, damage):
    args, write, request, receipt, completed, videos = done_batch
    if damage == "missing":
        completed["outputs"].pop()
    elif damage == "early":
        stamp = time.time_ns() - 55_000_000_000
        os.utime(videos[0], ns=(stamp, stamp))
    elif damage == "modified":
        videos[0].write_bytes(b"replaced")
    elif damage == "failed":
        completed["fails"] = ["one runner take failed"]
    elif damage == "unfinished":
        request.unlink()
    elif damage == "escape":
        completed["outputs"][0] = "../../unrelated.mp4"
    write(receipt, completed, -20)
    assert importer.main([*args, "--emit-manifest"]) == 1
    read = capsys.readouterr()
    assert not read.out
    assert "导入失败" in read.err


def test_apply_retries_same_atomic_metadata_after_connection_loss(done_batch, capsys, monkeypatch):
    args, _, _, _, _, videos = done_batch
    monkeypatch.setenv("PICOTOO_MAC_CORE_URL", "http://localhost")
    monkeypatch.setenv("PICOTOO_EXECUTOR_TOKEN", "fixture-only")
    monkeypatch.setattr(importer.time, "sleep", lambda _: None)
    posts = []

    class Response:
        status_code = 200

        def json(self):
            return {"episode_id": "demo", "existing_count": 2, "inserted_count": 0}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, url, **kwargs):
            assert url.endswith("/api/v1/episodes/import")
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False
            assert "files" not in kwargs
            posts.append(kwargs["json"])
            if len(posts) == 1:
                raise requests.ConnectionError("committed response lost")
            return Response()

    monkeypatch.setattr(requests, "Session", Session)
    assert importer.main([*args, "--apply"]) == 0
    assert posts[0] == posts[1]
    assert json.loads(capsys.readouterr().out)["existing_count"] == 2
    assert [video.read_bytes() for video in videos] == [b"fake take 1", b"fake take 2"]


@pytest.fixture
def has_retakes(done_batch):
    args, write, _, receipt, _, videos = done_batch
    root = Path(args[1])
    board = root / importer.BOARD
    retake_jobs = {
        "out": "../clips",
        "jobs": [
            {
                "id": "cut_S01b",
                "seconds": 4,
                "first": "../clips/first.png",
                "prompt": "A second reading.",
                "seeds": [101, 102, 103],
                "w": 640,
                "h": 960,
            }
        ],
    }
    write(board / "retake.json", retake_jobs, -16)
    write(receipt.with_name("retake.json"), {"runner": importer.RUNNER, "jobs": "retake.json"}, -14)
    retake_videos = [videos[0].with_name(f"cut_S01b_v{i}.mp4") for i in (1, 2, 3)]
    for i, file in enumerate(retake_videos, 1):
        file.write_bytes(f"retake {i}".encode("ascii"))
        stamp = time.time_ns() - 10_000_000_000
        os.utime(file, ns=(stamp, stamp))
    retake_receipt = {
        "task": "retake",
        "runner": importer.RUNNER,
        "ok": True,
        "returncode": 0,
        "fails": [],
        "outputs": [f"clips\\{file.name}" for file in retake_videos],
    }
    written = receipt.with_name("retake.result.json")
    write(written, retake_receipt, -5)
    mapping = [{"receipt": written.name, "shots": {"cut_S01b": "S01"}}]
    mapping_file = root / "mapping.json"
    write(mapping_file, mapping, 0)
    return [*args, "--retakes", str(mapping_file)], write, mapping, written, retake_receipt


def test_retake_merges_original_take_numbers_and_per_source_technical_expectations(
    has_retakes,
    capsys,
    monkeypatch,
):
    args, *_ = has_retakes
    monkeypatch.setattr(importer, "_technical_qc", lambda path, job: {"seconds": job["seconds"]})
    assert importer.main([*args, "--emit-manifest", "--probe"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert [shot["shot_id"] for shot in manifest["episode"]["shots"]] == ["S01"]
    assert manifest["episode"]["target_seconds"] == 3.5
    assert manifest["episode"]["shots"][0]["video"]["seeds"] == [42, 12]
    candidates = manifest["candidates"]
    assert [(c["shot_id"], c["take"], c["seed"]) for c in candidates] == [
        ("S01", 1, 42),
        ("S01", 2, 12),
        ("S01", 1, 101),
        ("S01", 2, 102),
        ("S01", 3, 103),
    ]
    assert [c["qc"]["seconds"] for c in candidates] == [3.5, 3.5, 4, 4, 4]
    assert len({c["source_id"] for c in candidates}) == 5
    assert len({c["path"] for c in candidates}) == 5
    assert all("decision" not in c for c in candidates)


@pytest.mark.parametrize(
    "bad",
    [
        "duplicate-entry",
        "baseline-receipt",
        "outside",
        "unknown-shot",
        "extra-source",
        "wrong-source",
        "partial",
        "combined-limit",
        "duplicate-video",
    ],
)
def test_invalid_retake_batch_cannot_submit_or_write_a_manifest(
    has_retakes,
    done_batch,
    bad,
    capsys,
    monkeypatch,
):
    args, write, mapping, retake_receipt, result = has_retakes
    _, _, _, base_receipt, original_result, _ = done_batch
    if bad == "duplicate-entry":
        mapping.append(mapping[0])
    elif bad == "baseline-receipt":
        mapping[0]["receipt"] = base_receipt.name
    elif bad == "outside":
        mapping[0]["receipt"] = "../../../another project/retake.result.json"
    elif bad == "unknown-shot":
        mapping[0]["shots"]["cut_S01b"] = "S02"
    elif bad == "extra-source":
        mapping[0]["shots"]["unused"] = "S01"
    elif bad == "wrong-source":
        mapping[0]["shots"] = {"missing": "S01"}
    elif bad == "partial":
        result["outputs"].pop()
        write(retake_receipt, result, -5)
    elif bad == "combined-limit":
        monkeypatch.setattr(importer, "MAX_CANDIDATES", 4)
    elif bad == "duplicate-video":
        duplicate = retake_receipt.with_name("duplicate.result.json")
        write(
            duplicate.with_name("duplicate.json"),
            {"runner": importer.RUNNER, "jobs": "jobs.json"},
            -40,
        )
        write(duplicate, {**original_result, "task": "duplicate"}, -20)
        mapping[0] = {"receipt": duplicate.name, "shots": {"cut_S01": "S01"}}
    write(Path(args[-1]), mapping, 0)
    monkeypatch.setattr(importer, "_apply", lambda *_: pytest.fail("partial network submit"))
    assert importer.main([*args, "--apply"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "导入失败" in captured.err
