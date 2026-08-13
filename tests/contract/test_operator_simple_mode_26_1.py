from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
VERSION = ROOT / "src" / "picotoopet_core" / "product-version.txt"
SHELL_XAML = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Views" / "ShellWindow.xaml"

def test_version() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "2.3.26.1"

def test_simple_sidebar() -> None:
    xaml = SHELL_XAML.read_text(encoding="utf-8")
    for title in ("首页", "待我审核", "进行中", "已完成", "高级"):
        assert title in xaml
