from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_research_gateway_release_files_exist() -> None:
    # 契约边界：正式 Mac 包必须包含安装、验证、卸载、说明与可复现构建脚本。
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
    # 版本边界：Research Gateway 独立版本化，并继续排除未批准的小宇宙能力。
    version = (ROOT / "research_gateway" / "VERSION").read_text(encoding="utf-8").strip()
    installer = (
        ROOT / "deploy" / "macos" / "research_gateway" / "INSTALL_RESEARCH_GATEWAY.command"
    ).read_text(encoding="utf-8")

    assert version == "2.3.27.1"
    assert "xiaoyuzhou" not in installer.lower()
    assert "picotoopet_core" not in installer


def test_installer_only_binds_existing_research_toolchain() -> None:
    # 安装边界：更新包只检测/绑定已有工具，不得偷偷安装或升级共享环境。
    installer = (
        ROOT / "deploy" / "macos" / "research_gateway" / "INSTALL_RESEARCH_GATEWAY.command"
    ).read_text(encoding="utf-8")

    forbidden_mutations = [
        "brew install",
        "pipx install",
        "pipx upgrade",
        "npm install",
        "agent-reach install",
    ]
    for mutation in forbidden_mutations:
        assert mutation not in installer

    for binary in ["agent-reach", "opencli", "mcporter", "gh", "yt-dlp"]:
        assert f"command -v {binary}" in installer

    assert "scrapling-mcp-local" in installer
    assert ".codex/mcp-servers/thunderbit" in installer
    assert "不会安装、升级或覆盖" in installer
