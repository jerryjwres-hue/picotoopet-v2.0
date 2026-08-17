"""Crawl4AI Research Adapter 独立 Mac arm64 包的交付与回滚契约。"""

from __future__ import annotations

import os
import subprocess
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


def test_python_selector_skips_incompatible_generic_python(
    tmp_path: Path,
) -> None:
    installer = (PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )
    start = installer.index("is_compatible_python() {")
    end = installer.index("\n# 前置检测：", start)
    selector_functions = installer[start:end]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    generic = fake_bin / "python3"
    versioned = fake_bin / "python3.12"
    # generic 模拟 macOS 自带旧 Python：任何兼容性探测都失败。
    generic.write_text("#!/bin/bash\nexit 99\n", encoding="utf-8")
    # versioned 模拟已安装的兼容 Python：兼容性探测成功。
    versioned.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    generic.chmod(0o755)
    versioned.chmod(0o755)

    harness = tmp_path / "selector.sh"
    harness.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f"venv_dir={tmp_path / 'missing-venv'}\n"
        f"{selector_functions}\n"
        "select_compatible_python\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    env["PICOTOOPET_PYTHON_BIN"] = str(generic)
    completed = subprocess.run(
        ["/bin/bash", str(harness)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.stdout.strip() == str(versioned)


def test_missing_python_diagnostic_has_bash32_safe_variable_boundaries() -> None:
    installer = (PACKAGE_DIR / "INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command").read_text(
        encoding="utf-8"
    )

    # macOS 自带 Bash 3.2 + set -u：变量紧贴全角括号必须使用显式 ${...} 边界。
    safe_line = 'echo "当前 PATH 的 python3：${current_python}（${current_version}）" >&2'
    assert safe_line in installer
    assert '$current_python（' not in installer
    assert '$current_version）' not in installer

    # 在目标机器使用的 /bin/bash 上真实执行该诊断表达式；macOS CI 因此会覆盖 Bash 3.2。
    completed = subprocess.run(
        [
            "/bin/bash",
            "-uc",
            f'current_python=/usr/bin/python3; current_version=3.9; {safe_line}',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "当前 PATH 的 python3：/usr/bin/python3（3.9）" in completed.stderr


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
