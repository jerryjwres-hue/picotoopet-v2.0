"""Static Mac provenance and bounded restart invariant for preflight branch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEAD = "${{ github.event.pull_request.head.sha || github.sha }}"

def test_native_mac_build_uses_exact_pr_head_for_checkout_and_label():
    for path in (".github/workflows/macos-core-slice-b-ci.yml",
                 ".github/workflows/macos-worker-slice-c-ci.yml"):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert source.count("ref: " + HEAD) >= 2
        assert HEAD in source.split("--version-label", 1)[1]

def test_worker_plist_has_bounded_crash_restart():
    source = (ROOT / "deploy/macos/phase23-worker/worker-lib.sh").read_text(encoding="utf-8")
    assert '"KeepAlive": True' in source
    assert '"RunAtLoad": True' in source
    assert '"ThrottleInterval": 30' in source

def test_authorized_video_goal_creative_is_not_rejected_as_unknown_worker_type():
    # ── CLI registers this exact local video handler when resident model is healthy. ──
    source = (ROOT / "deploy/macos/phase23-worker/worker-lib.sh").read_text(
        encoding="utf-8"
    )
    assert source.count('"autonomous.goal_creative.v1"') == 3
    assert "unexpected Worker task type" in source
