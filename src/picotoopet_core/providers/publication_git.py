"""Phase 10E 固定 Git 远端发布执行器。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


class PublicationGitError(RuntimeError):
    """固定 Publication Git 失败码。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublicationGitPublisher:
    """只允许 exact SHA -> fixed namespaced ref 的 Git 操作。"""

    _SHA = re.compile(r"^[0-9a-f]{40}$")
    _REMOTE_REF = re.compile(
        r"^refs/heads/picotoopet/commit-candidates/"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )

    def __init__(self, repository: Path) -> None:
        self.repository = repository.expanduser().resolve(strict=True)

    def verify_base(self, repo_url: str, base_ref: str, base_commit: str) -> None:
        """要求远端开发基线仍精确等于批准时的 immutable base。"""

        if not self._SHA.fullmatch(base_commit):
            raise PublicationGitError("PUBLICATION_PROVENANCE_INVALID")
        if not self._safe_base_ref(base_ref):
            raise PublicationGitError("PUBLICATION_BASE_POLICY")
        self._validate_repository_config()
        actual = self._read_remote(repo_url, f"refs/heads/{base_ref}")
        if actual != base_commit:
            raise PublicationGitError("PUBLICATION_BASE_MOVED")

    def read_remote_ref(self, repo_url: str, remote_ref: str) -> str | None:
        """读取一个 exact remote ref，不使用模糊 ref 匹配。"""

        if not self._REMOTE_REF.fullmatch(remote_ref):
            raise PublicationGitError("PUBLICATION_REMOTE_REF_POLICY")
        self._validate_repository_config()
        return self._read_remote(repo_url, remote_ref)

    def ensure_remote_ref(self, repo_url: str, remote_ref: str, commit_sha: str) -> list[str]:
        """幂等发布 exact commit；存在不同 SHA 时绝不覆盖。"""

        if not self._REMOTE_REF.fullmatch(remote_ref) or not self._SHA.fullmatch(commit_sha):
            raise PublicationGitError("PUBLICATION_REMOTE_REF_POLICY")
        self._validate_repository_config()
        current = self._read_remote(repo_url, remote_ref)
        if current is not None:
            if current != commit_sha:
                raise PublicationGitError("PUBLICATION_REMOTE_REF_CONFLICT")
            return ["remote_ref_exact", "idempotent_remote_ref_reuse"]

        self._run(
            "push",
            "--no-verify",
            repo_url,
            f"{commit_sha}:{remote_ref}",
            timeout=120,
        )
        verified = self._read_remote(repo_url, remote_ref)
        if verified != commit_sha:
            raise PublicationGitError("PUBLICATION_REMOTE_VERIFY_FAILED")
        return ["remote_ref_created", "remote_ref_exact"]

    def _read_remote(self, repo_url: str, ref: str) -> str | None:
        result = self._run(
            "ls-remote",
            "--refs",
            repo_url,
            ref,
            timeout=60,
        )
        lines = [line for line in result.splitlines() if line.strip()]
        if not lines:
            return None
        if len(lines) != 1:
            raise PublicationGitError("PUBLICATION_REMOTE_RESPONSE_INVALID")
        parts = lines[0].split("\t")
        if len(parts) != 2 or parts[1] != ref or not self._SHA.fullmatch(parts[0]):
            raise PublicationGitError("PUBLICATION_REMOTE_RESPONSE_INVALID")
        return parts[0]

    def _validate_repository_config(self) -> None:
        """拒绝会改写 publication URL 或 push destination 的本地 Git 配置。"""

        raw = self._run("config", "--local", "--null", "--list", timeout=30)
        for entry in raw.split("\0"):
            if not entry:
                continue
            key, separator, _value = entry.partition("\n")
            if not separator:
                continue
            lowered = key.lower()
            dangerous = (
                lowered.startswith("remote.") and lowered.endswith(".pushurl")
            ) or (
                lowered.startswith("remote.") and lowered.endswith(".vcs")
            ) or (
                lowered.startswith("url.") and lowered.endswith(".insteadof")
            ) or (
                lowered.startswith("url.") and lowered.endswith(".pushinsteadof")
            )
            if dangerous:
                raise PublicationGitError("PUBLICATION_GIT_CONFIG_POLICY")

    def _run(self, *arguments: str, timeout: int) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self._safe_environment(),
            timeout=timeout,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise PublicationGitError("PUBLICATION_GIT_FAILED")
        try:
            return result.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise PublicationGitError("PUBLICATION_REMOTE_RESPONSE_INVALID") from error

    @staticmethod
    def _safe_base_ref(value: str) -> bool:
        return bool(
            value
            and len(value) <= 200
            and value.lower() not in {"main", "master"}
            and not value.startswith("/")
            and not value.endswith("/")
            and ".." not in value
            and "//" not in value
            and all(ord(character) >= 33 for character in value)
        )

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        environment = {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
        environment["GIT_TERMINAL_PROMPT"] = "0"
        return environment
