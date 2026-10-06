from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "windows" / "desktop" / "scripts" / "Build-Phase2WindowsRelease.ps1"


def test_release_builder_resolves_sdk_from_desktop_global_json_not_caller_cwd() -> None:
    text = BUILDER.read_text(encoding="utf-8-sig")

    assert re.search(
        r'\$globalJson\s*=\s*Join-Path\s+\$desktopRoot\s+"global\.json"',
        text,
    )
    assert "Get-Content -LiteralPath $globalJson -Raw | ConvertFrom-Json" in text
    assert re.search(
        r'\$requiredSdkVersion\s*=\s*\[string\]\$globalJsonData\.sdk\.version',
        text,
    )
    assert re.search(
        r'Invoke-NativeCommand\s+-FilePath\s+\$dotnet\s+-Arguments\s+@\("--version"\)\s+-WorkingDirectory\s+\$desktopRoot',
        text,
    )
    assert text.count("-WorkingDirectory $desktopRoot") >= 8
    assert "Windows 发布必须使用 .NET SDK $requiredSdkVersion" in text
    assert '"10.0.302"' not in text
