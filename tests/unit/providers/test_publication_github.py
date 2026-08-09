from __future__ import annotations

import json
from pathlib import Path

import pytest

from picotoopet_core.providers.publication_github import (
    PublicationGitHubClient,
    PublicationGitHubError,
)


def fake_gh(tmp_path: Path) -> Path:
    state = tmp_path / "state.json"
    executable = tmp_path / "fake-gh.py"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state = Path(__file__).with_name('state.json')
args = sys.argv[1:]
if args[:3] == ['auth', 'status', '--hostname']:
    raise SystemExit(0)
if args[:2] == ['pr', 'list']:
    if state.exists():
        print(state.read_text())
    else:
        print('[]')
    raise SystemExit(0)
if args[:2] == ['pr', 'create']:
    repo = args[args.index('--repo') + 1]
    base = args[args.index('--base') + 1]
    head = args[args.index('--head') + 1]
    commit = 'b' * 40
    record = [{
        'number': 42,
        'url': f'https://github.com/{repo}/pull/42',
        'isDraft': True,
        'baseRefName': base,
        'headRefName': head,
        'headRefOid': commit,
        'state': 'OPEN',
    }]
    state.write_text(json.dumps(record))
    print(record[0]['url'])
    raise SystemExit(0)
raise SystemExit(91)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_ensure_draft_pr_creates_then_verifies_exact_identity(tmp_path: Path) -> None:
    client = PublicationGitHubClient(fake_gh(tmp_path))
    result = client.ensure_draft_pr(
        repository_slug="jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/safe-base",
        head_branch="picotoopet/commit-candidates/11111111-1111-1111-1111-111111111111",
        commit_sha="b" * 40,
        title="fixed title",
        body="fixed body",
    )
    assert result.number == 42
    assert result.head_sha == "b" * 40
    assert result.is_draft is True
    assert "pr_created" in result.validation_checks
    assert "pr_exact" in result.validation_checks


def test_ensure_draft_pr_recovers_exact_existing_draft(tmp_path: Path) -> None:
    executable = fake_gh(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps([
            {
                "number": 9,
                "url": "https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/9",
                "isDraft": True,
                "baseRefName": "feature/safe-base",
                "headRefName": "picotoopet/commit-candidates/22222222-2222-2222-2222-222222222222",
                "headRefOid": "b" * 40,
                "state": "OPEN",
            }
        ]),
        encoding="utf-8",
    )
    client = PublicationGitHubClient(executable)
    result = client.ensure_draft_pr(
        repository_slug="jerryjwres-hue/picotoopet-v2.0",
        base_ref="feature/safe-base",
        head_branch="picotoopet/commit-candidates/22222222-2222-2222-2222-222222222222",
        commit_sha="b" * 40,
        title="fixed title",
        body="fixed body",
    )
    assert result.number == 9
    assert result.validation_checks == ["pr_exact", "idempotent_pr_reuse"]


def test_existing_wrong_head_is_a_conflict(tmp_path: Path) -> None:
    executable = fake_gh(tmp_path)
    (tmp_path / "state.json").write_text(
        json.dumps([
            {
                "number": 10,
                "url": "https://github.com/jerryjwres-hue/picotoopet-v2.0/pull/10",
                "isDraft": True,
                "baseRefName": "feature/safe-base",
                "headRefName": "picotoopet/commit-candidates/33333333-3333-3333-3333-333333333333",
                "headRefOid": "c" * 40,
                "state": "OPEN",
            }
        ]),
        encoding="utf-8",
    )
    client = PublicationGitHubClient(executable)
    with pytest.raises(PublicationGitHubError, match="PUBLICATION_PR_CONFLICT"):
        client.ensure_draft_pr(
            repository_slug="jerryjwres-hue/picotoopet-v2.0",
            base_ref="feature/safe-base",
            head_branch="picotoopet/commit-candidates/33333333-3333-3333-3333-333333333333",
            commit_sha="b" * 40,
            title="fixed title",
            body="fixed body",
        )
