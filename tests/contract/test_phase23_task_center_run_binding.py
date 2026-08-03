"""Task Center 只读 Run.Text 绑定回归测试。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_CENTER_XAML = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Views"
    / "Pages"
    / "TaskCenterPage.xaml"
)


def test_task_center_read_only_run_bindings_are_explicitly_one_way() -> None:
    """只读 Priority 与 TimeoutSeconds 不得使用 Run.Text 的默认绑定方向。"""

    xaml = TASK_CENTER_XAML.read_text(encoding="utf-8")

    assert 'Text="{Binding Priority, Mode=OneWay}"' in xaml
    assert 'Text="{Binding TimeoutSeconds, Mode=OneWay}"' in xaml
