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
    assert "详细信息已写入脱敏日志" in code
    assert "操作没有完成；任务状态仍由 Mac Core 保存" in view_model


def test_simple_completed_task_detail_reuses_fixed_result_view_model() -> None:
    view_model = read("ViewModels/OperatorTaskListPageViewModel.cs")
    detail = read("ViewModels/TaskDetailViewModel.cs")

    assert "new TaskDetailViewModel(_session, task)" in view_model
    assert 'TaskType == "research.search"' in detail
    assert "GetResearchResultAsync" in detail
    assert "ResearchResult" in detail
