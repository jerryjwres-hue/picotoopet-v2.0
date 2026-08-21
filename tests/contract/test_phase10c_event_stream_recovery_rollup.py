"""Current product must retain the verified cold-start recovery behavior."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PRODUCT_VERSION = "2.3.27.1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rollup_uses_current_version_on_canonical_release_surfaces() -> None:
    version_file = ROOT / "src/picotoopet_core/product-version.txt"
    goal = json.loads(read(ROOT / "contracts/release/project-goal-invariants.json"))

    assert read(version_file).strip() == EXPECTED_PRODUCT_VERSION
    assert goal["windows"]["product_version"]["value"] == EXPECTED_PRODUCT_VERSION


def test_rollup_retains_the_23125_cold_start_recovery_behavior() -> None:
    event_stream = read(
        ROOT
        / "windows/desktop/src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs"
    )
    smoke = read(
        ROOT
        / "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/EventStreamColdStartSmokeTests.cs"
    )
    program = read(
        ROOT
        / "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs"
    )

    assert "DeferPingWhileEventsPending" in event_stream
    assert "_pendingPings.Clear();" in event_stream
    assert "ThrowIfPongExpired" in smoke
    assert "EventStreamColdStartSmokeTests.RunAsync" in program


def test_published_exe_self_test_covers_cold_start_recovery() -> None:
    self_test = read(
        ROOT / "windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs"
    )
    for required in (
        "VerifyColdStartEventStreamRecovery();",
        '["event_stream_cold_start_recovery"] = "pass"',
        'GetField("_channel"',
        'GetField("_pendingPings"',
        'GetMethod("ThrowIfPongExpired"',
        "PHASE10C_EVENT_STREAM_RECOVERY_SELF_TEST=PASS",
        "PHASE10C_EVENT_STREAM_RECOVERY_SELF_TEST=FAIL",
    ):
        assert required in self_test
