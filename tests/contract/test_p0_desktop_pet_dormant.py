"""Prevent deferred desk-pet art from blocking the canonical film pipeline.

These are source-only assertions; no desktop art, WPF boot or GPU is required.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/windows-phase2-release.yml"
SMOKE = ROOT / "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs"
BUILDER = ROOT / "windows/desktop/scripts/Build-Phase2WindowsRelease.ps1"
PANEL = ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.Maotai.cs"
MANUAL = ROOT / "docs/p0_296/REAL_23_V31_ARCHITECTURE_GATES.md"


class DormantDesktopPetContractTests(unittest.TestCase):
    """Desk pet may return only through a future explicit opt-in product decision."""

    def test_full_desktop_pet_workflow_is_manual_only(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        events = source.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", events)
        self.assertNotRegex(events, r"(?m)^  (?:pull_request|push|schedule|workflow_run):")
        self.assertIn("Optional Desktop Pet Full Release (manual only)", source)

    def test_default_windows_smoke_never_executes_optional_art_gate(self):
        source = SMOKE.read_text(encoding="utf-8")
        self.assertEqual(source.count("--desktop-pet-acceptance-only"), 2)
        first_default = source.index("            VerifyLatencyPercentiles();")
        pet_branch = source.index('args.Contains("--desktop-pet-acceptance-only"')
        self.assertLess(pet_branch, first_default)
        self.assertIn("MaotaiNaturalMotionV2AcceptanceSmokeTests.Run();", source[pet_branch:first_default])
        self.assertNotIn("MaotaiNaturalMotionV2AcceptanceSmokeTests.Run();", source[first_default:])
        self.assertNotIn("MaotaiAssetPixelValidationSmokeTests.Run();", source[first_default:])

    def test_manual_full_release_retains_real_art_acceptance(self):
        source = BUILDER.read_text(encoding="utf-8")
        scope = re.search(
            r'if \(\$ValidationScope -eq "Full"\)\s*\{[\s\S]*?'
            r'--desktop-pet-acceptance-only[\s\S]*?\}',
            source,
        )
        self.assertIsNotNone(scope)
        self.assertIn("UiPreview", source)
        self.assertIn('ValidateSet("Full", "UiPreview")', source)

    def test_runtime_keeps_extension_slot_off_and_preserves_status_panel(self):
        source = PANEL.read_text(encoding="utf-8")
        self.assertIn("DesktopPetV2Enabled = false;", source)
        self.assertRegex(
            source, r"if \(!DesktopPetV2Enabled\)\s*\{[\s\S]*?"
            r"MaotaiV2Root.Visibility = Visibility.Collapsed;[\s\S]*?return;",
        )
        self.assertIn("Loaded            += MaotaiPet_Loaded;", source)

    def test_architecture_manual_declares_dormant_nonblocking_extension(self):
        source = MANUAL.read_text(encoding="utf-8")
        self.assertIn("桌宠 V2 冻结", source)
        self.assertIn("仅手动触发", source)
        self.assertIn("不再阻塞", source)


if __name__ == "__main__":
    unittest.main()
