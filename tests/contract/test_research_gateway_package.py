from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_research_gateway_release_files_exist() -> None:
    required = [
        ROOT / "research_gateway" / "VERSION",
        ROOT / "research_gateway" / "gateway.py",
        ROOT / "deploy" / "macos" / "research_gateway" / "INSTALL_RESEARCH_GATEWAY.command",
        ROOT / "deploy" / "macos" / "research_gateway" / "VERIFY_RESEARCH_GATEWAY.command",
        ROOT / "deploy" / "macos" / "research_gateway" / "UNINSTALL_RESEARCH_GATEWAY.command",
        ROOT / "deploy" / "macos" / "research_gateway" / "README_INSTALL_CN.txt",
        ROOT / "scripts" / "mac" / "research_gateway" / "Build-ResearchGatewayPackage.sh",
        ROOT / "scripts" / "mac" / "research_gateway" / "Test-ResearchGatewayPackage.sh",
    ]

    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    assert missing == []


def test_gateway_has_independent_version_and_excludes_xiaoyuzhou() -> None:
    version = (ROOT / "research_gateway" / "VERSION").read_text(encoding="utf-8").strip()
    installer = (
        ROOT / "deploy" / "macos" / "research_gateway" / "INSTALL_RESEARCH_GATEWAY.command"
    ).read_text(encoding="utf-8")

    assert version == "2.3.27.1"
    assert "xiaoyuzhou" not in installer.lower()
    assert "picotoopet_core" not in installer


def test_installer_exposes_ci_fixture_mode_without_external_dependency_install() -> None:
    installer = (
        ROOT / "deploy" / "macos" / "research_gateway" / "INSTALL_RESEARCH_GATEWAY.command"
    ).read_text(encoding="utf-8")

    assert "PICOTOOPET_RESEARCH_SKIP_EXTERNAL_INSTALL" in installer
    assert "pipx" in installer
    assert "@jackwener/opencli" in installer
    assert "agent-reach" in installer
