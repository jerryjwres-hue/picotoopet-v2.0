from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows/desktop/src/PicotooPet.Desktop"
VIEWS = DESKTOP / "Views"
APP_XAML = DESKTOP / "App.xaml"
MANIFEST = DESKTOP / "app.manifest"

_FONT_SIZE = re.compile(r'FontSize="(?P<size>\d+(?:\.\d+)?)"')


def test_windows_uses_per_monitor_v2_dpi_awareness() -> None:
    source = MANIFEST.read_text(encoding="utf-8")
    assert "PerMonitorV2" in source
    assert "true/pm" in source


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


def test_opaque_operator_pages_do_not_hardcode_tiny_fonts() -> None:
    """正常业务界面不得继续使用 8–11 DIP 小字；透明桌宠表面单独治理。"""

    offenders: list[str] = []
    for path in sorted(VIEWS.rglob("*.xaml")):
        relative = path.relative_to(VIEWS).as_posix()
        if relative == "FloatingPetWindow.xaml" or relative.startswith("Controls/"):
            continue
        source = path.read_text(encoding="utf-8")
        for match in _FONT_SIZE.finditer(source):
            size = float(match.group("size"))
            if size < 12:
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{relative}:{line} FontSize={size:g}")
    assert not offenders, "Tiny operator fonts remain:\n" + "\n".join(offenders)
