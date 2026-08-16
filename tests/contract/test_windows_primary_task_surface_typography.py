from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Views" / "Pages"
PRIMARY_TASK_SURFACES = (
    "OperatorTaskListPage.xaml",
    "TaskCenterPage.xaml",
    "ResultsPage.xaml",
    "TaskDetailWindow.xaml",
)


def test_primary_task_and_result_surfaces_do_not_force_tiny_text() -> None:
    for filename in PRIMARY_TASK_SURFACES:
        source = (PAGES / filename).read_text(encoding="utf-8-sig")
        assert 'FontSize="12"' not in source, filename
        assert 'FontSize="13"' not in source, filename


def test_primary_task_and_result_surfaces_keep_14_dip_body_text() -> None:
    for filename in PRIMARY_TASK_SURFACES:
        source = (PAGES / filename).read_text(encoding="utf-8-sig")
        assert 'FontSize="14"' in source, filename
