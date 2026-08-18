from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"


def read(relative: str) -> str:
    return (DESKTOP / relative).read_text(encoding="utf-8-sig")


def test_task_center_keeps_existing_operational_metadata_while_adding_detail_route() -> None:
    xaml = read("Views/Pages/TaskCenterPage.xaml")

    for required in (
        'Text="原始状态"',
        'Text="{Binding Status, Mode=OneWay}"',
        'Text="创建时间"',
        'Text="{Binding CreatedAt, Mode=OneWay, StringFormat={}{0:yyyy-MM-dd HH:mm:ss zzz}}"',
        'Text="更新时间"',
        'Text="{Binding UpdatedAt, Mode=OneWay, StringFormat={}{0:yyyy-MM-dd HH:mm:ss zzz}}"',
        'Text="生成时间"',
        'Text="{Binding GeneratedAtText, Mode=OneWay}"',
        'Click="OpenTaskDetail_Click"',
        'MouseDoubleClick="TaskList_DoubleClick"',
    ):
        assert required in xaml


def test_results_center_keeps_result_identity_and_task_metadata() -> None:
    xaml = read("Views/Pages/ResultsPage.xaml")

    for required in (
        "TaskId",
        "ResultId",
        "DisplayType",
        "DisplayStatus",
        "UpdatedAt",
        'Click="OpenTaskDetail_Click"',
    ):
        assert required in xaml
