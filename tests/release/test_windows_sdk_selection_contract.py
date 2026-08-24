from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"


def test_release_builder_resolves_sdk_from_desktop_global_json_not_caller_cwd() -> None:
    text = BUILDER.read_text(encoding="utf-8-sig")

    assert '$globalJson = Join-Path $desktopRoot "global.json"' in text
    assert "Get-Content -LiteralPath $globalJson -Raw | ConvertFrom-Json" in text
    assert "$requiredSdkVersion = [string]$globalJsonData.sdk.version" in text
    assert "WorkingDirectory" in text
    assert "$desktopRoot" in text
    assert "Windows 发布必须使用 .NET SDK $requiredSdkVersion" in text
    assert '"10.0.302"' not in text
