from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows/desktop/src/PicotooPet.Desktop"
APP_XAML = DESKTOP / "App.xaml"
APP_CODE = DESKTOP / "App.xaml.cs"
PROJECT = DESKTOP / "PicotooPet.Desktop.csproj"
MANIFEST = DESKTOP / "app.manifest"
TASK_LIST = DESKTOP / "Views/Pages/OperatorTaskListPage.xaml"


def test_windows_uses_per_monitor_v2_dpi_awareness() -> None:
    project = PROJECT.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert "<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>" in project
    assert "<dpiAware" not in manifest
    assert "<dpiAwareness" not in manifest


def test_application_defines_readable_typography_scale() -> None:
    source = APP_XAML.read_text(encoding="utf-8")
    for token in (
        'x:Key="CaptionText"',
        'x:Key="SecondaryText"',
        'x:Key="BodyText"',
        'x:Key="EmphasizedBodyText"',
        'x:Key="SectionHeadingText"',
        'x:Key="PageHeadingText"',
    ):
        assert token in source
    assert '<Setter Property="FontSize" Value="14" />' in source
    assert 'TextFormattingMode" Value="Display"' in source


def test_all_loaded_operator_text_has_effective_12_dip_floor() -> None:
    """旧 XAML 的局部小字号也必须在运行时被统一夹到 12 DIP，桌宠表面除外。"""

    source = APP_CODE.read_text(encoding="utf-8")
    assert "MinimumOperatorFontSize = 12.0" in source
    assert "EventManager.RegisterClassHandler" in source
    assert "typeof(TextBlock)" in source
    assert "text.FontSize = MinimumOperatorFontSize" in source
    assert "TextFormattingMode.Display" in source
    assert "TextRenderingMode.ClearType" in source
    assert "AssistantPetPanel or FloatingPetWindow" in source


def test_new_task_list_surface_has_no_sub_12_dip_operator_text() -> None:
    source = TASK_LIST.read_text(encoding="utf-8")
    for forbidden in ('FontSize="8', 'FontSize="9', 'FontSize="10', 'FontSize="11'):
        assert forbidden not in source
