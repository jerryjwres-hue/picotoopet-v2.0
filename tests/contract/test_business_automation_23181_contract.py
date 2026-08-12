from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_business_automation_required_surfaces_exist() -> None:
    required = (
        "src/picotoopet_core/db/migration_011.py",
        "src/picotoopet_core/business/models.py",
        "src/picotoopet_core/business/repository.py",
        "src/picotoopet_core/business/archive.py",
        "src/picotoopet_core/business/store.py",
        "src/picotoopet_core/business/upload.py",
        "src/picotoopet_core/business/preprocess.py",
        "src/picotoopet_core/business/profiles.py",
        "src/picotoopet_core/business/local_intelligence.py",
        "src/picotoopet_core/business/quality.py",
        "src/picotoopet_core/business/execution.py",
        "src/picotoopet_core/business/service.py",
        "src/picotoopet_core/api/routes/business_automation.py",
        "windows/desktop/src/PicotooPet.Desktop.Core/Contracts/BusinessAutomationContracts.cs",
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.BusinessAutomation.cs",
        "windows/desktop/src/PicotooPet.Desktop/Services/BusinessBridgeService.cs",
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml",
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs",
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessAutomationWpfSmokeTests.cs",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == [], f"2.3.18.1 business automation surfaces are missing: {missing}"


def test_business_automation_security_boundary_is_closed() -> None:
    models = _read("src/picotoopet_core/business/models.py")
    adapter = _read("src/picotoopet_core/business/local_intelligence.py")
    execution = _read("src/picotoopet_core/business/execution.py")
    release_goal = _read("contracts/release/project-goal-invariants.json")

    assert "reviews.voice_of_customer.v1" in models
    assert "ideas.pattern_analysis.v1" in models
    assert "business.local_intelligence.v1" in execution
    assert "local.intelligence.v1" in execution
    assert "loopback" in adapter.lower()
    assert '"database_schema": 11' in release_goal
    assert '"automatic_paid_ai": false' in release_goal
    assert '"automatic_comfyui": false' in release_goal
    assert '"max_model_attempts_per_stage": 2' in release_goal
    for forbidden in ("subprocess.Popen", "os.system(", "shell=True", "comfyui"):
        assert forbidden not in execution.lower()


def test_windows_business_bridge_is_fixed_bounded_and_non_executable() -> None:
    bridge = _read("windows/desktop/src/PicotooPet.Desktop/Services/BusinessBridgeService.cs")
    client = _read(
        "windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.BusinessAutomation.cs"
    )
    navigation = _read("windows/desktop/src/PicotooPet.Desktop/Navigation/NavigationRoute.cs")

    for required in (
        '"PicotooPet", "BusinessBridge"',
        '"Inbox"',
        '"Outbox"',
        '"Quarantine"',
        '"Submitted"',
        "UploadChunkBytes = 4 * 1024 * 1024",
        "local.intelligence.v1",
    ):
        source = client if "UploadChunkBytes" in required else bridge
        if required == "local.intelligence.v1":
            source = _read(
                "windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs"
            )
        assert required in source
    assert "BusinessAutomation" in navigation
    for forbidden in (
        "Process.Start",
        "PowerShell",
        "cmd.exe",
        "ModelInput",
        "PromptInput",
        "EndpointInput",
        "CommandInput",
    ):
        assert forbidden not in bridge


def test_windows_business_page_has_no_free_model_prompt_or_command_inputs() -> None:
    page = _read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml"
    )
    view_model = _read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs"
    )
    smoke = _read(
        "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/BusinessAutomationWpfSmokeTests.cs"
    )
    assert "业务自动化" in page
    assert "Measure(new Size(1100, 800))" in smoke
    assert "Arrange(new Rect(0, 0, 1100, 800))" in smoke
    assert "UpdateLayout()" in smoke
    assert "BindingMode.OneWay" in smoke
    for forbidden in (
        "PromptInput",
        "ModelInput",
        "EndpointInput",
        "CommandInput",
        "TaskTypeInput",
        "WebView",
    ):
        assert forbidden not in page
        assert forbidden not in view_model


def test_business_automation_is_retained_in_current_rollup() -> None:
    # Version retention gate     18.1 behavior remains present in the cumulative 25.1 product.
    assert _read("src/picotoopet_core/product-version.txt").strip() == "2.3.25.1"
