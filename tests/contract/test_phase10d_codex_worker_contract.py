from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    path = ROOT / relative
    assert path.is_file(), f"Phase 10D-A 缺少正式文件：{relative}"
    return path.read_text(encoding="utf-8")


def test_codex_adapter_uses_fixed_headless_json_protocol() -> None:
    adapter = _read("src/picotoopet_core/worker/codex_adapter.py")

    for required in (
        'TASK_TYPE = "provider.codex.handoff-v1"',
        '"exec"',
        '"--json"',
        '"--ephemeral"',
        '"workspace-write"',
        '"never"',
        '"plugins"',
        '"false"',
        "stdin",
    ):
        assert required in adapter

    assert "shell=True" not in adapter
    assert "--dangerously-bypass-approvals-and-sandbox" not in adapter
    assert "--add-dir" not in adapter
    assert "git push" not in adapter
    assert "git commit" not in adapter


def test_codex_worktree_is_session_exclusive_and_cleanup_is_mandatory() -> None:
    worktree = _read("src/picotoopet_core/worker/codex_worktree.py")

    for required in (
        "session_id",
        "base_commit",
        "git worktree add",
        "git worktree remove",
        "allowed_write",
        "symlink",
        "cleanup",
    ):
        assert required in worktree

    assert "main" in worktree
    assert "master" in worktree
    assert "force" not in worktree.lower()


def test_fake_codex_fixture_is_the_only_ci_provider() -> None:
    fixture = _read("tests/fixtures/codex/fake_codex_jsonl.py")
    workflow = _read(".github/workflows/macos-worker-slice-c-ci.yml")

    assert "PICOTOOPET_CODEX_EXECUTABLE" in workflow
    assert "fake_codex_jsonl.py" in workflow
    assert "turn.completed" in fixture
    assert "provider_usage_unknown" in fixture
    assert "OPENAI_API_KEY" not in workflow
    assert "CODEX_API_KEY" not in workflow
