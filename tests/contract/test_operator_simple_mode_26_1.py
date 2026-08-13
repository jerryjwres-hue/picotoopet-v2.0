"""2.3.26.1 Operator Simple Mode source-level contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = ROOT / "src" / "picotoopet_core" / "product-version.txt"
ROUTES = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Navigation"
    / "NavigationRoute.cs"
)
SHELL = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "ViewModels"
    / "ShellViewModel.cs"
)


def test_operator_simple_mode_targets_2_3_26_1() -> None:
    """26.1 必须拥有明确的共享产品版本身份。"""

    assert VERSION.read_text(encoding="utf-8").strip() == "2.3.26.1"


def test_operator_routes_are_added_without_deleting_advanced_routes() -> None:
    """默认简单模式新增五个入口，但工程路由仍必须可由高级首页访问。"""

    route_code = ROUTES.read_text(encoding="utf-8")
    for route in (
        "OperatorHome",
        "OperatorReview",
        "OperatorInProgress",
        "OperatorCompleted",
        "AdvancedHome",
    ):
        assert route in route_code

    for historical_route in (
        "Dashboard",
        "Projects",
        "TaskCenter",
        "Results",
        "Approvals",
        "CloudDevelopment",
        "Automation",
        "BusinessAutomation",
        "Health",
        "Diagnostics",
        "Settings",
    ):
        assert historical_route in route_code


def test_default_sidebar_copy_is_exactly_the_simple_operator_set() -> None:
    """Shell 默认操作入口固定为用户批准的五项，不重新平铺工程页。"""

    shell_code = SHELL.read_text(encoding="utf-8")
    for title in ("首页", "待我审核", "进行中", "已完成", "高级"):
        assert f'"{title}"' in shell_code
