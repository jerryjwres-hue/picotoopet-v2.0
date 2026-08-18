"""Product identity changes must be additive and preserve the existing Maotai host."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_INFO = ROOT / "windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs"
SHELL = ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml"
SHELL_CODE = ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml.cs"


def test_windows_identity_is_picotoopet_ai_superpower_v1() -> None:
    version_text = VERSION_INFO.read_text(encoding="utf-8")
    shell_code = SHELL_CODE.read_text(encoding="utf-8")

    assert 'public const string ProductName = "PicotooPet AI";' in version_text
    assert 'public const string SuperpowerLabel = "superpower v1.0";' in version_text
    assert 'WindowTitle => $"{ProductName} {Current}"' in version_text
    assert 'ControlCenterSubtitle => $"{SuperpowerLabel} · Control Center · v{Current}"' in version_text

    # Keep the existing XAML/layout intact: Shell normalizes only the legacy brand TextBlocks at runtime.
    assert "using PicotooPet.Desktop.Versioning;" in shell_code
    assert "ApplyProductIdentity(this);" in shell_code
    assert 'string.Equals(textBlock.Text, "Picotoo Pet AI", StringComparison.Ordinal)' in shell_code
    assert "textBlock.Text = ProductVersionInfo.ProductName;" in shell_code


def test_identity_upgrade_preserves_existing_shell_and_maotai_integration_surface() -> None:
    shell_text = SHELL.read_text(encoding="utf-8")

    assert '<controls:AssistantPetPanel x:Name="AssistantPet"' in shell_text
    assert 'ItemsSource="{Binding NavigationItems, Mode=OneWay}"' in shell_text
    assert '<views:NavigationContentHost x:Name="ContentHost"' in shell_text
    assert 'Text="{Binding ControlCenterSubtitle, Mode=OneWay}"' in shell_text
