from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = ROOT / "src" / "picotoopet_core" / "product-version.txt"
SHELL = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Views" / "ShellWindow.xaml"


def test_version() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "2.3.26.1"


def test_simple_sidebar_is_fixed_and_advanced_is_landing_page() -> None:
    xaml = SHELL.read_text(encoding="utf-8")
    expected = {
        "SimpleHomeButton": "首页",
        "SimpleReviewButton": "待我审核",
        "SimpleActiveButton": "进行中",
        "SimpleCompletedButton": "已完成",
        "SimpleAdvancedButton": "高级",
    }
    for name, title in expected.items():
        assert f'x:Name="{name}"' in xaml
        assert f'Content="{title}"' in xaml
    assert 'x:Name="AdvancedHomePanel"' in xaml
    assert 'ItemsSource="{Binding NavigationItems}"' not in xaml
