from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1] / "director-console-native-v2" / "native" / "PVP.DirectorConsole"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle!r}")


def main() -> int:
    xaml = read("MainWindow.xaml")
    models = read("Models/ApiModels.cs")
    client = read("Services/DirectorCoreClient.cs")
    manager = read("Services/DirectorCoreProcessManager.cs")
    vm = read("ViewModels/MainWindowViewModel.cs")

    for needle in (
        "批量选择",
        "删除选中",
        "恢复选中",
        "高级详情",
        "系统与执行准备",
        "自动导演",
        "协同导演",
        "人工控制",
    ):
        require(xaml, needle, "Chinese UX marker")

    for needle in ("DisplayDepartment", "DisplayMode"):
        require(models, needle, "localized model property")

    for needle in (
        "PreviewBatchDeleteAsync",
        "BatchDeleteAsync",
        "PreviewBatchRestoreAsync",
        "BatchRestoreAsync",
    ):
        require(client, needle, "typed client method")

    for needle in (
        "RunSupervisorAsync",
        "ConfirmOwnedProcessUnhealthyAsync",
        "TimeSpan.FromMilliseconds(500)",
        "TimeSpan.FromSeconds(8)",
    ):
        require(manager, needle, "supervisor marker")

    for needle in ("RefreshPollingSnapshotAsync", "部分数据刷新失败"):
        require(vm, needle, "lightweight polling marker")

    forbidden = ("WebView2", "RunStaticCanaryAsync", "queue_prompt", "/prompt")
    for path in ROOT.rglob("*"):
        if path.suffix.lower() not in {".cs", ".xaml"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                raise AssertionError(f"forbidden Native runtime marker {needle!r} in {path.relative_to(ROOT)}")

    print("N6E3_RUNTIME_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"N6E3_RUNTIME_CONTRACT=FAIL: {exc}", file=sys.stderr)
        raise
