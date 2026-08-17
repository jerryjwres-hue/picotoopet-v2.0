"""Crawl4AI Research Adapter 独立 Mac arm64 包的交付与回滚契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "deploy" / "macos" / "crawl4ai_research_adapter"
SCRIPT_DIR = ROOT / "scripts" / "mac" / "crawl4ai_research_adapter"


def test_crawl4ai_adapter_release_files_exist() -> None:
    # 交付边界：只新增 Mac Research adapter 包，不新增 Windows 安装入口。
    required = [
        ROOT / "research_gateway" / "crawler_adapter.py",
        ROOT / "research_gateway" / "crawl4ai_runner.py",
        ROOT / "research_gateway" / "CRAWL4AI_ADAPTER_VERSION",
        PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command",
        PACKAGE_DIR / "VERIFY_CRAWL4AI_RESEARCH_ADAPTER.command",
        PACKAGE_DIR / "ROLLBACK_CRAWL4AI_RESEARCH_ADAPTER.command",
        PACKAGE_DIR / "README_INSTALL_CN.txt",
        SCRIPT_DIR / "Build-Crawl4AIResearchAdapterPackage.sh",
        SCRIPT_DIR / "Test-Crawl4AIResearchAdapterPackage.sh",
    ]

    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    assert missing == []


def test_installer_is_arm64_isolated_and_never_upgrades_shared_toolchain() -> None:
    installer = (PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )

    assert 'test "$(uname -m)" = "arm64"' in installer
    assert "~/.local/share/picotoopet" in installer or ".local/share/picotoopet" in installer
    assert "crawl4ai==0.9.2" in installer
    assert "PLAYWRIGHT_BROWSERS_PATH" in installer
    assert "python -m venv" in installer or '"$python_bin" -m venv' in installer
    # 与现有 PicotooPet runtime requires-python >=3.12,<3.14 对齐，只检测、不升级系统 Python。
    assert "(3, 12) <= sys.version_info[:2] < (3, 14)" in installer
    assert "Python 3.12-3.13" in installer

    forbidden = [
        "sudo ",
        "brew install",
        "brew upgrade",
        "pip install --upgrade",
        "pipx upgrade",
        "npm install",
        "scrapling install",
        "playwright install chrome",
    ]
    for mutation in forbidden:
        assert mutation not in installer.lower()


def test_installer_selects_a_compatible_python_instead_of_first_python3() -> None:
    installer = (PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )

    # 实机回归：macOS /usr/bin/python3 可能是 3.9，不能因为它先出现在 PATH 就直接失败。
    assert "select_compatible_python" in installer
    assert "python3.13" in installer
    assert "python3.12" in installer
    assert "/opt/homebrew/bin/python3.13" in installer
    assert "/opt/homebrew/bin/python3.12" in installer
    assert "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" in installer
    assert "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" in installer
    assert 'python_bin="$(command -v python3)"' not in installer
    # 安装状态写入也必须继续使用已验证解释器，不能悄悄回退到系统 python3。
    assert '"$python_bin" - "$install_state"' in installer
    assert 'python3 - "$install_state"' not in installer


def test_verify_runs_real_timeout_404_network_and_content_limit_fixtures() -> None:
    verifier = (PACKAGE_DIR / "VERIFY_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )

    assert "https://www.rfc-editor.org/rfc/rfc999999.html" in verifier
    assert "https://httpbin.org/delay/5" in verifier
    assert '"timeout"' in verifier
    assert "--timeout-seconds 1" in verifier
    assert "https://picotoopet-crawl4ai.invalid/" in verifier
    assert "https://www.rfc-editor.org/rfc/rfc9110.html" in verifier


def test_installer_only_detects_existing_scrapling_gateway_and_worker() -> None:
    installer = (PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )

    assert "scrapling-mcp-local" in installer
    assert "ResearchGateway" in installer
    assert "MacWorker" in installer or "Worker" in installer
    assert "command -v python3" in installer
    assert "command -v docker" in installer


def test_rollback_never_deletes_scrapling_gateway_worker_or_chrome_state() -> None:
    rollback = (PACKAGE_DIR / "ROLLBACK_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    ).lower()

    forbidden = [
        "rm -rf \"$home/library/application support/picotoopet/researchgateway\"",
        "rm -rf \"$home/library/application support/picotoopet/macworker\"",
        "rm -rf \"$home/.local/bin/scrapling-mcp-local\"",
        "library/application support/google/chrome",
        ".config/google-chrome",
    ]
    for mutation in forbidden:
        assert mutation not in rollback

    assert "gateway.py.pre-crawl4ai" in rollback
    assert "created_venv" in rollback


def test_package_docs_keep_account_write_and_captcha_capabilities_disabled() -> None:
    documentation = (PACKAGE_DIR / "README_INSTALL_CN.txt").read_text(encoding="utf-8").lower()

    for denied in [
        "captcha",
        "登录",
        "cookie",
        "密码",
        "token",
        "点赞",
        "关注",
        "评论",
        "发帖",
        "私信",
        "下单",
    ]:
        assert denied in documentation
