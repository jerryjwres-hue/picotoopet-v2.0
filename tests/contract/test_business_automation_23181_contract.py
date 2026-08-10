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
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml",
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == [], f"2.3.18.1 missing business automation surfaces: {missing}"


def test_business_automation_security_boundary_is_closed() -> None:
    models = _read("src/picotoopet_core/business/models.py")
    adapter = _read("src/picotoopet_core/business/local_intelligence.py")
    execution = _read("src/picotoopet_core/business/execution.py")

    assert "reviews.voice_of_customer.v1" in models
    assert "ideas.pattern_analysis.v1" in models
    assert "business.local_intelligence.v1" in execution
    assert "local.intelligence.v1" in execution
    assert "loopback" in adapter.lower()
    for forbidden in ("subprocess.Popen", "os.system(", "shell=True", "comfyui"):
        assert forbidden not in execution.lower()


def test_windows_business_page_has_no_free_model_prompt_or_command_inputs() -> None:
    page = _read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/BusinessAutomationPage.xaml"
    )
    view_model = _read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/BusinessAutomationPageViewModel.cs"
    )
    assert "业务自动化" in page
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
