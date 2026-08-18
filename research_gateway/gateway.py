"""Structured, read-only command dispatcher for the PicotooPet Research Gateway."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse


def _adapter_bootstrap_python(*, version_info=None, environ=None, home=None):
    """Resolve only the fixed adapter-private Python when this interpreter is unsupported."""

    current = tuple((version_info if version_info is not None else sys.version_info)[:2])
    if (3, 12) <= current < (3, 14):
        return None

    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else Path(home)
    configured_root = str(environment.get("PICOTOOPET_CRAWL4AI_ROOT", "")).strip()
    adapter_root = (
        Path(configured_root).expanduser()
        if configured_root
        else home_path / ".local" / "share" / "picotoopet" / "research" / "crawl4ai"
    )
    candidate = adapter_root / "venv" / "bin" / "python"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def _bootstrap_adapter_python() -> None:
    """Re-exec the adapter-patched Gateway before Python-3.12-only runtime code executes."""

    current = sys.version_info[:2]
    if (3, 12) <= current < (3, 14):
        return
    candidate = _adapter_bootstrap_python()
    if candidate is None:
        raise RuntimeError(
            "Research Gateway requires Python 3.12-3.13 and the Crawl4AI private runtime is missing"
        )
    script = Path(__file__).resolve()
    os.execv(str(candidate), [str(candidate), str(script), *sys.argv[1:]])


_bootstrap_adapter_python()

from dataclasses import asdict, dataclass  # noqa: E402

from research_gateway.crawler_adapter import (  # noqa: E402
    CrawlerProviderError,
    CrawlRequest,
    build_installed_crawler_adapter,
    extract_public_urls,
    render_search_envelope,
)

READ_CAPABILITIES = {
    "research.search",
    "research.web.read",
    "research.web.crawl",
    "research.web.extract",
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
_WEB_OUTPUTS = {"markdown", "html", "text"}
_WEB_CRAWL_MODES = {
    "static": ("scrapling.get", 90),
    "dynamic": ("scrapling.fetch", 120),
    "stealth": ("scrapling.stealthy_fetch", 150),
}
_AUTO_CRAWLER = object()


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

    def __init__(
        self,
        *,
        runner: Runner = run_subprocess,
        crawler_adapter: object = _AUTO_CRAWLER,
    ) -> None:
        self._runner = runner
        # 自动绑定只认项目固定安装路径；显式 None 用于兼容/回滚与单元测试。
        self._crawler_adapter = (
            build_installed_crawler_adapter(runner=runner)
            if crawler_adapter is _AUTO_CRAWLER
            else crawler_adapter
        )

    def dispatch(self, capability: str, params: dict[str, object]) -> CommandResult:
        if capability not in READ_CAPABILITIES:
            raise PolicyError(f"Research Gateway 2.3.27.1 is read-only: {capability}")

        # research.search 保持唯一上层能力名；crawler provider 仅在 Gateway 内部可见。
        if capability == "research.search":
            return self._dispatch_search(params)

        builders = {
            "research.web.read": self._build_web_read,
            "research.web.crawl": self._build_web_crawl,
            "research.web.extract": self._build_web_extract,
            "research.social.search": self._build_social_search,
            "research.video.search": self._build_video_search,
            "research.video.transcript": self._build_video_transcript,
            "research.github.search": self._build_github_search,
            "research.community.search": self._build_community_search,
            "research.company.lookup": self._build_company_lookup,
        }
        argv, timeout_seconds = builders[capability](params)
        return self._runner(argv, timeout_seconds)

    def _dispatch_search(self, params: dict[str, object]) -> CommandResult:
        """Run existing search discovery, then optionally enrich bounded result URLs."""

        argv, timeout_seconds = self._build_search(params)
        search_result = self._runner(argv, timeout_seconds)
        if search_result.returncode != 0 or self._crawler_adapter is None:
            return search_result

        query = self._required_text(params, "query")
        limits = getattr(self._crawler_adapter, "limits", None)
        maximum_pages = getattr(limits, "max_pages", 1)
        urls = extract_public_urls(search_result.stdout, maximum=maximum_pages)
        if not urls:
            return search_result

        documents = []
        failures = 0
        for url in urls:
            try:
                # 默认单页读取深度为 0；CrawlerAdapter 内部决定 Crawl4AI → Scrapling fallback。
                documents.append(self._crawler_adapter.crawl(CrawlRequest(url=url)))
            except CrawlerProviderError:
                failures += 1

        if not documents and failures:
            # 对上层只暴露稳定错误，不泄露 provider stderr、cookie、token 或浏览器状态。
            return CommandResult(returncode=69, stdout="", stderr="crawler providers failed")
        if not documents:
            return search_result

        enriched = render_search_envelope(
            query=query,
            search_output=search_result.stdout,
            documents=documents,
        )
        return CommandResult(returncode=0, stdout=enriched, stderr="")

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

    @staticmethod
    def _external_http_url(params: dict[str, object], key: str = "url") -> str:
        url = GatewayDispatcher._required_text(params, key)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute http(s) URL")

        hostname = parsed.hostname.lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("url must target an external host")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("url must target an external host")
        return url

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
        url = self._external_http_url(params)
        return ["curl", "-fsSL", "--max-time", "60", f"https://r.jina.ai/{url}"], 70

    def _build_web_crawl(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(params, {"url", "mode"})
        url = self._external_http_url(params)
        mode_value = params.get("mode", "static")
        if not isinstance(mode_value, str):
            raise ValueError("mode must be a string")
        mode = mode_value.strip().lower()
        route = _WEB_CRAWL_MODES.get(mode)
        if route is None:
            raise ValueError(f"unsupported crawl mode: {mode}")
        selector, timeout_seconds = route
        return [
            "mcporter",
            "call",
            selector,
            f"url={url}",
            "extraction_type=markdown",
            "main_content_only=true",
        ], timeout_seconds

    def _build_web_extract(self, params: dict[str, object]) -> tuple[list[str], int]:
        self._validate_keys(
            params,
            {"url", "css_selector", "output", "schema", "allow_paid_backend"},
        )
        url = self._external_http_url(params)
        schema = params.get("schema")
        if schema is not None:
            if not isinstance(schema, dict) or not schema:
                raise ValueError("schema must be a non-empty object")
            allow_paid = params.get("allow_paid_backend", False)
            if not isinstance(allow_paid, bool):
                raise ValueError("allow_paid_backend must be a boolean")
            if not allow_paid:
                raise PolicyError(
                    "Thunderbit structured extraction consumes credits; "
                    "set allow_paid_backend=true only after explicit approval"
                )
            if "css_selector" in params or "output" in params:
                raise ValueError("schema extraction cannot be combined with css_selector or output")
            schema_json = json.dumps(schema, separators=(",", ":"), sort_keys=True)
            if len(schema_json) > 20_000:
                raise ValueError("schema is too large")
            return [
                "mcporter",
                "call",
                "thunderbit.thunderbit_extract",
                f"url={url}",
                f"schema={schema_json}",
            ], 150

        if "allow_paid_backend" in params:
            raise ValueError("allow_paid_backend is only valid with schema extraction")
        output_value = params.get("output", "markdown")
        if not isinstance(output_value, str):
            raise ValueError("output must be a string")
        output = output_value.strip().lower()
        if output not in _WEB_OUTPUTS:
            raise ValueError(f"unsupported output: {output}")

        argv = [
            "mcporter",
            "call",
            "scrapling.get",
            f"url={url}",
            f"extraction_type={output}",
            "main_content_only=true",
        ]
        css_selector = params.get("css_selector")
        if css_selector is not None:
            if not isinstance(css_selector, str) or not css_selector.strip():
                raise ValueError("css_selector must be a non-empty string")
            if len(css_selector) > 500:
                raise ValueError("css_selector is too long")
            argv.append(f"css_selector={css_selector.strip()}")
        return argv, 90

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
        url = self._external_http_url(params)
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
