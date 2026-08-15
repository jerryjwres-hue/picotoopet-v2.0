"""Structured, read-only command dispatcher for the PicotooPet Research Gateway."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

READ_CAPABILITIES = {
    "research.search",
    "research.web.read",
    "research.social.search",
    "research.video.search",
    "research.video.transcript",
    "research.github.search",
    "research.community.search",
    "research.company.lookup",
}

_SOCIAL_PLATFORMS = {"twitter", "reddit", "xiaohongshu", "facebook", "instagram", "xueqiu"}
_GITHUB_KINDS = {"repos", "code", "issues", "prs"}
_REQUIRED_TOOLS = ("agent-reach", "opencli", "mcporter", "gh", "yt-dlp", "bili", "curl")
_LINKEDIN_USERNAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class PolicyError(RuntimeError):
    """Raised when a request crosses the frozen read-only capability boundary."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Serializable subprocess result returned by the gateway."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], int], CommandResult]


def run_subprocess(argv: list[str], timeout_seconds: int) -> CommandResult:
    """Execute a trusted argv vector without invoking a shell."""

    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class GatewayDispatcher:
    """Translate abstract research capabilities into concrete read-only tool argv vectors."""

    def __init__(self, *, runner: Runner = run_subprocess) -> None:
        self._runner = runner

    def dispatch(self, capability: str, params: dict[str, object]) -> CommandResult:
        if capability not in READ_CAPABILITIES:
            raise PolicyError(f"Research Gateway 2.3.27.1 is read-only: {capability}")

        builders = {
            "research.search": self._build_search,
            "research.web.read": self._build_web_read,
            "research.social.search": self._build_social_search,
            "research.video.search": self._build_video_search,
            "research.video.transcript": self._build_video_transcript,
            "research.github.search": self._build_github_search,
            "research.community.search": self._build_community_search,
            "research.company.lookup": self._build_company_lookup,
        }
        argv, timeout_seconds = builders[capability](params)
        return self._runner(argv, timeout_seconds)

    @staticmethod
    def _validate_keys(params: dict[str, object], allowed: set[str]) -> None:
        unknown = sorted(set(params) - allowed)
        if unknown:
            raise ValueError(f"unsupported parameter: {unknown[0]}")

    @staticmethod
    def _required_text(params: dict[str, object], key: str) -> str:
        value = params.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _bounded_limit(params: dict[str, object], *, default: int = 5, maximum: int = 20) -> int:
        value = params.get("limit", default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError(f"limit must be an integer between 1 and {maximum}")
        return value

    def _build_search(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"query", "limit"})
        query = self._required_text(params, "query")
        limit = self._bounded_limit(params)
        expression = (
            "exa.web_search_exa("
            f"query: {json.dumps(query, ensure_ascii=False)}, numResults: {limit}"
            ")"
        )
        return ["mcporter", "call", expression], 90

    def _build_web_read(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"url"})
        url = self._required_text(params, "url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return ["curl", "-fsSL", "--max-time", "60", f"https://r.jina.ai/{url}"], 70

    def _build_social_search(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"platform", "query", "limit"})
        platform = self._required_text(params, "platform").lower()
        query = self._required_text(params, "query")
        limit = self._bounded_limit(params)
        if platform not in _SOCIAL_PLATFORMS:
            raise ValueError(f"unsupported platform: {platform}")
        if platform == "reddit":
            return ["opencli", "reddit", "search", query, "-f", "json"], 90
        if platform == "xiaohongshu":
            return ["opencli", "xiaohongshu", "search", query, "-f", "json"], 90
        if platform == "twitter":
            return ["opencli", "twitter", "search", query, "-f", "json"], 90
        return ["opencli", platform, "search", query, "--limit", str(limit), "-f", "json"], 90

    def _build_video_search(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"platform", "query", "limit"})
        platform = self._required_text(params, "platform").lower()
        query = self._required_text(params, "query")
        limit = self._bounded_limit(params)
        if platform == "youtube":
            return ["yt-dlp", f"ytsearch{limit}:{query}", "--flat-playlist", "--dump-json"], 120
        if platform == "bilibili":
            return ["bili", "search", query, "--type", "video"], 120
        raise ValueError(f"unsupported platform: {platform}")

    def _build_video_transcript(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"url", "languages"})
        url = self._required_text(params, "url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        languages = params.get("languages", "en.*,zh.*")
        if not isinstance(languages, str) or not languages.strip():
            raise ValueError("languages must be a non-empty string")
        return [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            languages.strip(),
            "--sub-format",
            "vtt",
            "--dump-single-json",
            url,
        ], 180

    def _build_github_search(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"query", "kind", "limit"})
        query = self._required_text(params, "query")
        kind = str(params.get("kind", "repos")).lower()
        limit = self._bounded_limit(params)
        if kind not in _GITHUB_KINDS:
            raise ValueError(f"unsupported GitHub search kind: {kind}")
        return ["gh", "search", kind, query, "--limit", str(limit)], 60

    def _build_community_search(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"community", "query", "limit"})
        community = self._required_text(params, "community").lower()
        translated = {
            "platform": "reddit" if community == "reddit" else community,
            "query": self._required_text(params, "query"),
            "limit": self._bounded_limit(params),
        }
        if community not in {"reddit", "xiaohongshu"}:
            raise ValueError(f"unsupported community: {community}")
        return self._build_social_search(translated)

    def _build_company_lookup(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"linkedin_username"})
        username = self._required_text(params, "linkedin_username")
        if not _LINKEDIN_USERNAME.fullmatch(username):
            raise ValueError("linkedin_username contains unsupported characters")
        expression = f'linkedin.get_person_profile(linkedin_username: "{username}")'
        return ["mcporter", "call", expression], 120


def health_snapshot() -> dict[str, object]:
    """Return process-level dependency presence without reading browser cookies or secrets."""

    tools = {name: shutil.which(name) is not None for name in _REQUIRED_TOOLS}
    return {
        "version": _read_version(),
        "read_only": True,
        "xiaoyuzhou_enabled": False,
        "tools": tools,
        "ready": all(tools.values()),
    }


def _read_version() -> str:
    return (Path(__file__).with_name("VERSION")).read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="picotoopet-research-gateway")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--capability")
    parser.add_argument("--params-json", default="{}")
    args = parser.parse_args(argv)

    if args.health:
        print(json.dumps(health_snapshot(), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.capability:
        parser.error("--capability is required unless --health is used")

    try:
        params = json.loads(args.params_json)
        if not isinstance(params, dict):
            raise ValueError("--params-json must decode to an object")
        result = GatewayDispatcher().dispatch(args.capability, params)
    except (PolicyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0 if result.returncode == 0 else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
