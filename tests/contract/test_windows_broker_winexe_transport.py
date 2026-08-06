"""Windows WinExe Mock Broker 实机传输回归。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop.Core" / "DevBroker" / "DevBrokerProcessRunner.cs"
SELF_TEST = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop" / "Services" / "AppSelfTest.cs"


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
