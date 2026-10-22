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


def test_standalone_worker_verify_accepts_dynamic_goal_creative(tmp_path):
    # ── Execute the real embedded verifier without Core, token or model access. ──
    import json
    import re
    import subprocess
    import sys

    script = (ROOT / "deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r'python3 - "\$runtime_root/state/worker-status.json" <<\x27PY\x27\n(.*?)\nPY\n',
        script,
        re.DOTALL,
    )
    assert match is not None
    status_file = tmp_path / "worker-status.json"

    def verdict(task_types):
        # ── The file is a disposable fixture, never the user Mac status file. ──
        status_file.write_text(
            json.dumps({"supported_task_types": task_types, "active_task_id": None}),
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, "-c", match.group(1), str(status_file)],
            capture_output=True,
            text=True,
            check=False,
        )

    base_types = ["system.diagnostic_snapshot", "system.noop"]
    good = verdict(base_types + ["autonomous.goal_creative.v1"])
    assert good.returncode == 0, good.stderr

    # ── Preserve fail-closed rejection of unregistered worker task types. ──
    bad = verdict(base_types + ["autonomous.unapproved_custom.v1"])
    assert bad.returncode != 0
    assert "unexpected Worker task type" in bad.stderr
