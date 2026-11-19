import json

import pytest


def sample(root):
    return {
        "episode": {
            "episode_id": "film",
            "title": "</script>片名",
            "edit": {"fps": 24},
            "shots": [{"shot_id": "S01", "beat": "观察", "emotion": "高兴"}],
        },
        "candidates": [
            {
                "kind": "video",
                "shot_id": "S01",
                "take": n,
                "seed": 100 + n,
                "sha256": str(n) * 64,
                "path": str(root / f"候选 #{n}.mp4"),
                "source_id": "batch",
                "jpeg_base64": "OMIT_PREVIEW",
            }
            for n in (1, 2)
        ],
    }


def notes(manifest, picked="pick"):
    return {
        "version": 1,
        "episode_id": "film",
        "decisions": [
            {
                **{k: item[k] for k in ("shot_id", "take", "sha256", "source_id")},
                "decision": picked if item["take"] == 1 else "reject",
                "note": "检查耳位",
            }
            for item in manifest["candidates"]
        ],
    }


def test_page_uses_local_clips_only_and_escapes_embedded_data(tmp_path):
    from scripts.windows.review_board import write_review_page

    manifest = sample(tmp_path)
    page = tmp_path / "看.html"
    manifest["candidates"][0]["seed"] = 2**63 - 1
    write_review_page(manifest, page)
    html = page.read_text(encoding="utf-8")
    assert "</script>片名" not in html
    assert "OMIT_PREVIEW" not in html
    assert "%23" in html and "file:" in html
    assert "导出审片记录" in html
    assert '"seed":"9223372036854775807"' in html
    assert "https://" not in html
    manifest["candidates"][0]["path"] = "https://example.test/movie.mp4"
    with pytest.raises(ValueError):
        write_review_page(manifest, page)
    assert page.read_text(encoding="utf-8") == html


def test_offline_decisions_match_bytes_and_source_and_are_atomic(tmp_path):
    from scripts.windows.review_board import apply_decisions

    manifest = sample(tmp_path)
    path = tmp_path / "notes.json"
    decisions = notes(manifest)
    decisions["decisions"][1]["sha256"] = "f" * 64
    path.write_text(json.dumps(decisions), encoding="utf-8")
    with pytest.raises(ValueError):
        apply_decisions(manifest, path)
    assert all("decision" not in c for c in manifest["candidates"])
    path.write_text(json.dumps(notes(manifest)), encoding="utf-8")
    apply_decisions(manifest, path)
    assert [(c["decision"], c["note"]) for c in manifest["candidates"]] == [
        ("pick", "检查耳位"),
        ("reject", "检查耳位"),
    ]


def test_cut_plan_marks_sources_without_creating_picks(tmp_path):
    from scripts.windows.review_board import write_review_page

    manifest = sample(tmp_path)
    plan = tmp_path / "cut.json"
    plan.write_text(
        json.dumps(
            {"root": "/another/editing/host", "shots": [{"video": "候选 #2.mp4", "in": 0.2}]}
        ),
        encoding="utf-8",
    )
    rough = tmp_path / "rough.mp4"
    rough.write_bytes(b"placeholder")
    dest = tmp_path / "review.html"
    write_review_page(manifest, dest, project_root=tmp_path, cut_plan=plan, cut_video=rough)
    data = json.loads(
        dest.read_text(encoding="utf-8")
        .split('<script id="batch" type="application/json">', 1)[1]
        .split("</script>", 1)[0]
    )
    assert [row["in_cut"] for row in data["candidates"]] == [False, True]
    assert data["cut_uri"] == rough.as_uri()
    assert all(row["decision"] is None for row in data["candidates"])
    plan.write_text(json.dumps({"shots": [{"video": "../other.mp4"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        write_review_page(manifest, dest, project_root=tmp_path, cut_plan=plan)


@pytest.mark.parametrize("change", ["two-picks", "duplicate", "episode", "source", "redo", "note"])
def test_bad_offline_decisions_are_refused(tmp_path, change):
    from scripts.windows.review_board import apply_decisions

    manifest = sample(tmp_path)
    record = notes(manifest)
    if change == "two-picks":
        record["decisions"][1]["decision"] = "pick"
    elif change == "duplicate":
        record["decisions"].append(record["decisions"][0])
    elif change == "episode":
        record["episode_id"] = "another"
    elif change == "source":
        record["decisions"][0]["source_id"] = "other"
    elif change == "redo":
        record["decisions"][0]["decision"] = "redo"
    else:
        record["decisions"][0]["note"] = "字" * 2001
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        apply_decisions(manifest, path)
