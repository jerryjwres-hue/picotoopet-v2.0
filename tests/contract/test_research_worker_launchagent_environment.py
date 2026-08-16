"""Research Worker 的真实 LaunchAgent 环境必须能发现已部署的本地工具。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_LIBRARY = ROOT / "deploy" / "macos" / "phase23-worker" / "worker-lib.sh"


def test_worker_launchagent_has_deterministic_research_tool_path() -> None:
    """launchd 不继承交互 shell PATH；Worker 必须显式绑定用户级与 Homebrew 工具路径。"""

    source = WORKER_LIBRARY.read_text(encoding="utf-8")
    for required in (
        "research_worker_path = os.pathsep.join(",
        'str(Path.home() / ".local" / "bin")',
        '"/opt/homebrew/bin"',
        '"/usr/local/bin"',
        '"/usr/bin"',
        '"/bin"',
        '"/usr/sbin"',
        '"/sbin"',
        '"PATH": research_worker_path',
    ):
        assert required in source


def test_worker_launchagent_does_not_depend_on_interactive_shell_initialization() -> None:
    """服务启动路径必须在 plist 中确定，不能依赖 .zshrc/.bashrc 或 shell profile。"""

    source = WORKER_LIBRARY.read_text(encoding="utf-8")
    for forbidden in (
        ".zshrc",
        ".zprofile",
        ".bashrc",
        ".bash_profile",
        "source ~/.profile",
    ):
        assert forbidden not in source
