"""Phase 10E 固定 GitHub Draft PR 适配器。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class PublicationGitHubError(RuntimeError):
    """固定 GitHub publication 错误码。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DraftPrResult:
    """经过二次读取确认的 Draft PR 安全摘要。"""

    number: int
    url: str
    head_sha: str
    is_draft: bool
    validation_checks: list[str]


class PublicationGitHubClient:
    """只暴露 exact repo/base/head 的 Draft PR 查询与创建。"""

    _MAX_OUTPUT_BYTES = 64 * 1024
    _SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    _SHA = re.compile(r"^[0-9a-f]{40}$")
    _BRANCH = re.compile(
        r"^picotoopet/commit-candidates/"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )

    def __init__(self, executable: Path) -> None:
        resolved = executable.expanduser().resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise PublicationGitHubError("PUBLICATION_AUTH_UNAVAILABLE")
        self.executable = resolved

    def ensure_draft_pr(
        self,
        *,
        repository_slug: str,
        base_ref: str,
        head_branch: str,
        commit_sha: str,
        title: str,
        body: str,
    ) -> DraftPrResult:
        """复用 exact Draft PR；不存在时创建一次并再次独立核验。"""

        self._validate_inputs(repository_slug, base_ref, head_branch, commit_sha, title, body)
        existing = self._list_prs(repository_slug, base_ref, head_branch)
        if existing:
            result = self._exact_result(
                existing,
                repository_slug=repository_slug,
                base_ref=base_ref,
                head_branch=head_branch,
                commit_sha=commit_sha,
            )
            return DraftPrResult(
                number=result.number,
                url=result.url,
                head_sha=result.head_sha,
                is_draft=True,
                validation_checks=["pr_exact", "idempotent_pr_reuse"],
            )

        self._run(
            "pr",
            "create",
            "--repo",
            repository_slug,
            "--base",
            base_ref,
            "--head",
            head_branch,
            "--draft",
            "--title",
            title,
            "--body",
            body,
            timeout=60,
        )
        created = self._list_prs(repository_slug, base_ref, head_branch)
        result = self._exact_result(
            created,
            repository_slug=repository_slug,
            base_ref=base_ref,
            head_branch=head_branch,
            commit_sha=commit_sha,
        )
        return DraftPrResult(
            number=result.number,
            url=result.url,
            head_sha=result.head_sha,
            is_draft=True,
            validation_checks=["pr_created", "pr_exact"],
        )

    def _list_prs(self, repository_slug: str, base_ref: str, head_branch: str) -> list[dict[str, object]]:
        output = self._run(
            "pr",
            "list",
            "--repo",
            repository_slug,
            "--base",
            base_ref,
            "--head",
            head_branch,
            "--state",
            "open",
            "--limit",
            "10",
            "--json",
            "number,url,isDraft,baseRefName,headRefName,headRefOid,state",
            timeout=30,
        )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise PublicationGitHubError("PUBLICATION_PR_RESPONSE_INVALID") from error
        if not isinstance(payload, list) or len(payload) > 10:
            raise PublicationGitHubError("PUBLICATION_PR_RESPONSE_INVALID")
        if any(not isinstance(item, dict) for item in payload):
            raise PublicationGitHubError("PUBLICATION_PR_RESPONSE_INVALID")
        return payload

    def _exact_result(
        self,
        records: list[dict[str, object]],
        *,
        repository_slug: str,
        base_ref: str,
        head_branch: str,
        commit_sha: str,
    ) -> DraftPrResult:
        if len(records) != 1:
            raise PublicationGitHubError("PUBLICATION_PR_CONFLICT")
        item = records[0]
        expected_url_prefix = f"https://github.com/{repository_slug}/pull/"
        number = item.get("number")
        url = item.get("url")
        exact = (
            isinstance(number, int)
            and number > 0
            and isinstance(url, str)
            and url == f"{expected_url_prefix}{number}"
            and item.get("isDraft") is True
            and item.get("baseRefName") == base_ref
            and item.get("headRefName") == head_branch
            and item.get("headRefOid") == commit_sha
            and str(item.get("state", "")).upper() == "OPEN"
        )
        if not exact:
            raise PublicationGitHubError("PUBLICATION_PR_CONFLICT")
        return DraftPrResult(
            number=number,
            url=url,
            head_sha=commit_sha,
            is_draft=True,
            validation_checks=["pr_exact"],
        )

    @classmethod
    def _validate_inputs(
        cls,
        repository_slug: str,
        base_ref: str,
        head_branch: str,
        commit_sha: str,
        title: str,
        body: str,
    ) -> None:
        if not cls._SLUG.fullmatch(repository_slug) or ".." in repository_slug:
            raise PublicationGitHubError("PUBLICATION_PR_POLICY")
        if (
            not base_ref
            or len(base_ref) > 200
            or base_ref.lower() in {"main", "master"}
            or ".." in base_ref
            or "//" in base_ref
            or any(ord(character) < 33 for character in base_ref)
        ):
            raise PublicationGitHubError("PUBLICATION_PR_POLICY")
        if not cls._BRANCH.fullmatch(head_branch) or not cls._SHA.fullmatch(commit_sha):
            raise PublicationGitHubError("PUBLICATION_PR_POLICY")
        if not title or len(title) > 240 or not body or len(body.encode("utf-8")) > 16 * 1024:
            raise PublicationGitHubError("PUBLICATION_PR_POLICY")
        if any(ord(character) < 9 for character in title + body):
            raise PublicationGitHubError("PUBLICATION_PR_POLICY")

    def _run(self, *arguments: str, timeout: int) -> str:
        try:
            result = subprocess.run(
                [str(self.executable), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._safe_environment(),
                timeout=timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PublicationGitHubError("PUBLICATION_PR_FAILED") from error
        if result.returncode != 0 or len(result.stdout) > self._MAX_OUTPUT_BYTES:
            raise PublicationGitHubError("PUBLICATION_PR_FAILED")
        try:
            return result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise PublicationGitHubError("PUBLICATION_PR_RESPONSE_INVALID") from error

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        environment = {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
        environment["GH_PROMPT_DISABLED"] = "1"
        return environment
