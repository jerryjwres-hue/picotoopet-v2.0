"""Windows WinExe Mock Broker 实机传输与启动边界回归。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
CORE = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop.Core"
RUNNER = CORE / "DevBroker" / "DevBrokerProcessRunner.cs"
CHILD = CORE / "DevBroker" / "MockProviderChild.cs"
PATHS = CORE / "DevBroker" / "BrokerSandboxPaths.cs"
SELF_TEST = DESKTOP / "Services" / "AppSelfTest.cs"
PROJECT = DESKTOP / "PicotooPet.Desktop.csproj"
PROGRAM = DESKTOP / "Program.cs"
APP = DESKTOP / "App.xaml.cs"
SESSION = DESKTOP / "Services" / "ControlCenterSession.Broker.cs"
PANEL = DESKTOP / "Views" / "Pages" / "BrokerSessionPanel.xaml"


def test_winexe_parent_reads_return_from_fixed_sandbox_file() -> None:
    """GUI 子进程不得依赖 Console stdout 作为唯一 Return 传输通道。"""

    source = RUNNER.read_text(encoding="utf-8")
    assert "paths.ReturnEnvelopePath" in source
    assert "ReadBoundedEnvelopeFile" in source
    assert "return ParseEnvelope(stdout);" not in source


def test_published_self_test_launches_real_broker_child_process() -> None:
    """正式发布 EXE 自检必须覆盖真实 WinExe -> child -> 固定文件闭环。"""

    source = SELF_TEST.read_text(encoding="utf-8")
    assert "VerifyPublishedBrokerChildProcess" in source
    assert 'checks["cloud_development_phase10b_broker_process"] = "pass"' in source
    assert "DevBrokerProcessRunner.RunAsync" in source


def test_mock_child_is_intercepted_before_wpf_application_bootstrap() -> None:
    """子模式必须在 Application/XAML/单实例锁创建前完成，避免实机 WPF 启动差异。"""

    project = PROJECT.read_text(encoding="utf-8")
    program = PROGRAM.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    assert "<StartupObject>PicotooPet.Desktop.Program</StartupObject>" in project
    assert "MockProviderChild.TryRun" in program
    assert "new App()" in program
    assert program.index("MockProviderChild.TryRun") < program.index("new App()")
    assert "application.InitializeComponent()" in program
    assert "MockProviderChild.TryRun" not in app


def test_parent_assigns_job_before_releasing_fixed_child_start_gate() -> None:
    """快速子进程不得在 Job Object 绑定完成前执行或退出。"""

    runner = RUNNER.read_text(encoding="utf-8")
    child = CHILD.read_text(encoding="utf-8")
    paths = PATHS.read_text(encoding="utf-8")

    assert "StartGatePath" in paths
    assert "ReleaseStartGate" in runner
    assert "WaitForStartGate" in child
    assert runner.index("job.Assign(process)") < runner.index("ReleaseStartGate(paths)")


def test_child_exit_codes_remain_bounded_and_visible_to_the_current_session() -> None:
    """实机失败不得再次被压缩为无法定位的通用 BROKER_CHILD_FAILED。"""

    runner = RUNNER.read_text(encoding="utf-8")
    session = SESSION.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")

    assert "MapChildFailure" in runner
    for fixed_code in (
        "BROKER_OUTPUT_INVALID",
        "BROKER_SANDBOX_IO_FAILED",
        "BROKER_SANDBOX_ACCESS_DENIED",
        "BROKER_DIGEST_FAILED",
    ):
        assert fixed_code in runner
    assert "failed with { FailureCode = exception.Code }" in session
    assert "SelectedSession.FailureCode" in panel
