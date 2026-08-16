from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def read(relative: str) -> str:
    return (DESKTOP / relative).read_text(encoding="utf-8-sig")


def test_simple_task_list_never_renders_raw_exception_messages() -> None:
    code = read("Views/Pages/OperatorTaskListPage.xaml.cs")
    view_model = read("ViewModels/OperatorTaskListPageViewModel.cs")

    assert "exception.Message" not in code
    assert "exception.Message" not in view_model
    assert "任务详情暂时无法安全显示" in code
    assert "任务本身没有被修改" in code
    assert "操作没有完成；任务状态仍由 Mac Core 保存" in view_model


def test_shell_and_app_never_render_raw_exception_messages() -> None:
    app = read("App.xaml.cs")
    shell = read("Views/ShellWindow.xaml.cs")

    assert "exception.Message" not in app
    assert "exception.Message" not in shell

    assert "初始化没有完成。你仍可在设置页重新配对" in app
    assert "退出时有资源未能正常释放" in app
    assert 'logger.Error("Control Center 初始化失败", exception)' in app
    assert '_logger?.Error("退出时释放资源失败", exception)' in app

    assert "连接没有完成。请检查 Mac 地址和设备令牌后重试" in shell
    assert '_logger.Error("连接 Mac Core 失败", exception)' in shell


def test_simple_completed_task_detail_reuses_fixed_result_view_model() -> None:
    view_model = read("ViewModels/OperatorTaskListPageViewModel.cs")
    detail = read("ViewModels/TaskDetailViewModel.cs")

    assert "new TaskDetailViewModel(_session, task)" in view_model
    assert 'ResearchTaskType = "research.search"' in detail
    assert "case ResearchTaskType:" in detail
    assert "GetResearchResultAsync" in detail
    assert "ResearchResult" in detail
    assert "当前类型尚未配置安全正文预览" in detail
