from scripts.detect_component_impact import classify


def test_windows_only_change_does_not_build_mac_components() -> None:
    impact = classify(
        [
            "windows/desktop/src/PicotooPet.Desktop/Views/Pages/ResultsPage.xaml",
            "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ResultsPageWpfLayoutSmokeTests.cs",
        ]
    )
    assert impact == {"core": False, "worker": False, "windows": True}


def test_core_approval_change_does_not_build_worker() -> None:
    impact = classify(
        [
            "src/picotoopet_core/approvals/service.py",
            "src/picotoopet_core/api/routes/approvals.py",
            "tests/integration/approvals/test_control_center_approval.py",
        ]
    )
    assert impact == {"core": True, "worker": False, "windows": False}


def test_worker_runtime_change_builds_worker_without_core_package() -> None:
    impact = classify(
        [
            "src/picotoopet_core/worker/runtime.py",
            "tests/integration/worker/test_diagnostic_worker_e2e.py",
        ]
    )
    assert impact == {"core": False, "worker": True, "windows": False}


def test_shared_dependency_change_builds_all_components() -> None:
    assert classify(["pyproject.toml"]) == {
        "core": True,
        "worker": True,
        "windows": True,
    }


def test_documentation_and_pr_evidence_build_nothing() -> None:
    impact = classify(
        [
            "docs/operations/acceptance.md",
            "docs/superpowers/plans/example.md",
        ]
    )
    assert impact == {"core": False, "worker": False, "windows": False}


def test_workflow_change_validates_only_its_native_component() -> None:
    assert classify([".github/workflows/macos-worker-slice-c-ci.yml"]) == {
        "core": False,
        "worker": True,
        "windows": False,
    }
