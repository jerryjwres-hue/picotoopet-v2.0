from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_phase10e_required_publication_surfaces_exist() -> None:
    required = (
        "src/picotoopet_core/db/migration_010.py",
        "src/picotoopet_core/providers/publication_models.py",
        "src/picotoopet_core/providers/publication_service.py",
        "src/picotoopet_core/providers/publication_git.py",
        "src/picotoopet_core/providers/publication_github.py",
        "src/picotoopet_core/providers/publication_execution.py",
        "src/picotoopet_core/providers/github_readiness.py",
        "src/picotoopet_core/api/routes/provider_publications.py",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == [], f"Phase 10E 缺少正式实现文件: {missing}"


def test_phase10e_security_boundary_is_frozen_in_source() -> None:
    service = _read("src/picotoopet_core/providers/publication_service.py")
    execution = _read("src/picotoopet_core/providers/publication_execution.py")
    git_runner = _read("src/picotoopet_core/providers/publication_git.py")
    github = _read("src/picotoopet_core/providers/publication_github.py")
    routes = _read("src/picotoopet_core/api/routes/provider_publications.py")

    assert 'APPROVAL_TYPE = "provider.publish.pr-create-v1"' in service
    assert "refs/heads/picotoopet/commit-candidates/" in service
    assert 'TASK_TYPE = "provider.publish.pr-create-v1"' in execution
    assert '"--no-verify"' in git_runner
    assert '"--force"' not in git_runner
    assert '"--draft"' in github
    assert "require_empty_body" in routes
    for forbidden in ('"merge"', '"release"'):
        assert forbidden not in execution.lower()


def test_phase10e_windows_surface_has_no_free_publication_inputs() -> None:
    page = _read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml"
    )
    view_model = _read(
        "windows/desktop/src/PicotooPet.Desktop/ViewModels/ProviderReviewViewModel.cs"
    )

    assert "准备 Push + Draft PR" in page
    assert "pr_ready != CI-green != merge-ready" in page
    assert "PreparePublicationCommand" in view_model
    assert "CanPreparePublication" in view_model
    for forbidden_binding in (
        "RepositoryInput",
        "BaseRefInput",
        "HeadRefInput",
        "PrTitleInput",
        "PrBodyInput",
        "RemoteRefInput",
    ):
        assert forbidden_binding not in page


def test_phase10e_is_retained_in_23201() -> None:
    assert _read("src/picotoopet_core/product-version.txt").strip() == "2.3.20.1"
