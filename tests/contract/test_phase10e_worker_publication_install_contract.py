from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "deploy/macos/phase23-worker/worker-lib.sh"
INSTALL = ROOT / "deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_plist_preserves_only_known_provider_publication_environment() -> None:
    source = read(LIB)
    for required in (
        "PICOTOO_PROVIDER_REPOSITORY",
        "PICOTOO_PROVIDER_WORKTREE_ROOT",
        "PICOTOO_CODEX_EXECUTABLE",
        "PICOTOO_GITHUB_CLI_EXECUTABLE",
        "preserved_environment",
        "github_cli_executable",
    ):
        assert required in source
    assert "EnvironmentVariables" in source
    assert "existing.get(" in source


def test_worker_installer_discovers_fixed_github_cli_without_installing_it() -> None:
    source = read(INSTALL)
    for required in (
        "discover_github_cli_executable",
        "/opt/homebrew/bin/gh",
        "/usr/local/bin/gh",
        "command -v gh",
        "write_worker_plist",
    ):
        assert required in source
    for forbidden in (
        "brew install gh",
        "sudo ",
        "curl ",
        "wget ",
    ):
        assert forbidden not in source


def test_worker_runtime_verifier_accepts_only_closed_registered_task_allowlist() -> None:
    source = read(LIB)
    for required in (
        "provider.codex.handoff-v1",
        "provider.adoption.apply-v1",
        "provider.commit.create-v1",
        "provider.publish.pr-create-v1",
        "system.diagnostic_snapshot",
        "system.noop",
        "unexpected Worker task type",
    ):
        assert required in source
