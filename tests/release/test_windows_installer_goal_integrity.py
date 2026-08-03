from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (
    ROOT
    / "windows"
    / "desktop"
    / "release"
    / "Install-Phase2Prebuilt.ps1"
)


def _installer() -> str:
    return INSTALLER.read_text(encoding="utf-8-sig")


def test_installer_requires_exact_native_wpf_goal_fields() -> None:
    text = _installer()

    required_checks = (
        'Assert-ManifestString -Manifest $manifest -Name "delivery_surface" -Expected "existing-native-wpf-desktop"',
        'Assert-ManifestString -Manifest $manifest -Name "ui_framework" -Expected "WPF"',
        'Assert-ManifestString -Manifest $manifest -Name "entry_executable" -Expected "Picotoo Pet AI.exe"',
        'Assert-ManifestString -Manifest $manifest -Name "integration_target" -Expected "TaskCenter"',
        'Assert-ManifestBoolean -Manifest $manifest -Name "browser_ui" -Expected $false',
        'Assert-ManifestBoolean -Manifest $manifest -Name "local_http_ui" -Expected $false',
        'Assert-ManifestBoolean -Manifest $manifest -Name "source_build_on_user_pc" -Expected $false',
    )
    for check in required_checks:
        assert check in text


def test_installer_requires_native_verification_and_install_permission() -> None:
    text = _installer()

    assert (
        'Assert-ManifestBoolean -Manifest $manifest -Name "native_ci_verified" -Expected $true'
        in text
    )
    assert (
        'Assert-ManifestBoolean -Manifest $manifest -Name "user_install_allowed" -Expected $true'
        in text
    )
    assert "if ($manifest.PSObject.Properties.Name -contains \"user_install_allowed\"" not in text


def test_installer_requires_native_wpf_payload_and_rejects_web_assets() -> None:
    text = _installer()

    assert 'Assert-ManifestPayloadContract -Manifest $manifest' in text
    assert '"Picotoo Pet AI.exe"' in text
    assert '"tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe"' in text
    assert 'forbidden web UI payload' in text
