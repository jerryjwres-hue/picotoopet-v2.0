from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_CENTER_XAML = REPO_ROOT / "windows/desktop/src/PicotooPet.Desktop/Views/Pages/TaskCenterPage.xaml"
APP_XAML_CS = REPO_ROOT / "windows/desktop/src/PicotooPet.Desktop/App.xaml.cs"


def test_task_center_read_only_run_bindings_are_explicitly_one_way() -> None:
    xaml = TASK_CENTER_XAML.read_text(encoding="utf-8")

    assert 'Text="{Binding Priority, Mode=OneWay}"' in xaml
    assert 'Text="{Binding TimeoutSeconds, Mode=OneWay}"' in xaml


def test_wpf_dispatcher_unhandled_exceptions_are_logged_and_contained() -> None:
    source = APP_XAML_CS.read_text(encoding="utf-8")

    assert "DispatcherUnhandledException += OnDispatcherUnhandledException" in source
    assert "logger.Error(\"WPF UI 未处理异常\", exception)" in source
    assert "eventArgs.Handled = true" in source
