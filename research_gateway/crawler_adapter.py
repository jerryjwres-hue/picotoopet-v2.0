"""Fixed, read-only crawler provider registry for the PicotooPet Research Gateway."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


class CrawlerProvider(StrEnum):
    """Closed provider identifiers; arbitrary provider names are intentionally unsupported."""

    CRAWL4AI = "crawl4ai"
    SCRAPLING = "scrapling"


CRAWLER_PROVIDER_ALLOWLIST = (
    CrawlerProvider.CRAWL4AI,
    CrawlerProvider.SCRAPLING,
)


@dataclass(frozen=True, slots=True)
class CrawlLimits:
    """Conservative limits shared by every crawler provider."""

    max_pages: int = 3
    max_depth: int = 0
    timeout_seconds: int = 30
    max_content_bytes: int = 262_144
    redirect_limit: int = 5
    concurrency: int = 2
    retry_limit: int = 1


@dataclass(frozen=True, slots=True)
class CrawlRequest:
    """A single read-only page request; deep crawling is deliberately absent."""

    url: str
    javascript: bool = False


@dataclass(frozen=True, slots=True)
class CrawlerDocument:
    """Normalized crawler output consumed by Research Gateway only."""

    title: str
    url: str
    source: str
    markdown: str
    provider: CrawlerProvider
    status_code: int | None = None


class CrawlerProviderError(RuntimeError):
    """Controlled provider failure with routing metadata but no secret-bearing stderr."""

    def __init__(
        self,
        message: str,
        *,
        provider: CrawlerProvider,
        captcha: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.captcha = captcha
        self.retryable = retryable


class ProcessResult(Protocol):
    """Minimal subprocess result shape shared with gateway.CommandResult."""

    returncode: int
    stdout: str
    stderr: str


ProcessRunner = Callable[[list[str], int], ProcessResult]


class Provider(Protocol):
    """Internal provider protocol; implementations are fixed at construction time."""

    provider: CrawlerProvider

    def crawl(self, request: CrawlRequest, limits: CrawlLimits) -> CrawlerDocument: ...


_HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def validate_public_http_url(url: str) -> str:
    """Reject non-HTTP, credential-bearing, localhost, and literal non-public destinations."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a public http(s) URL")
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be a public http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must be a public http(s) URL without credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("url must be a public http(s) URL")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("url must be a public http(s) URL")
    return normalized


def extract_public_urls(payload: str, *, maximum: int) -> list[str]:
    """Extract at most ``maximum`` public result URLs from JSON or textual search output."""

    if maximum < 1:
        return []
    candidates: list[str] = []
    try:
        decoded = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        decoded = None

    def visit(value: object) -> None:
        if len(candidates) >= maximum:
            return
        if isinstance(value, Mapping):
            direct = value.get("url")
            if isinstance(direct, str):
                candidates.append(direct)
            for child in value.values():
                visit(child)
                if len(candidates) >= maximum:
                    return
        elif isinstance(value, list):
            for child in value:
                visit(child)
                if len(candidates) >= maximum:
                    return

    if decoded is not None:
        visit(decoded)
    if not candidates:
        candidates.extend(_HTTP_URL_RE.findall(payload)[:maximum])

    accepted: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            url = validate_public_http_url(candidate.rstrip(".,);]"))
        except ValueError:
            continue
        if url not in seen:
            accepted.append(url)
            seen.add(url)
        if len(accepted) >= maximum:
            break
    return accepted


class CrawlerAdapter:
    """Route one page to Crawl4AI first, then one finite Scrapling fallback."""

    def __init__(
        self,
        *,
        crawl4ai: Provider,
        scrapling: Provider,
        limits: CrawlLimits | None = None,
    ) -> None:
        self._crawl4ai = crawl4ai
        self._scrapling = scrapling
        self.limits = limits or CrawlLimits()

    def crawl(self, request: CrawlRequest) -> CrawlerDocument:
        safe_request = CrawlRequest(
            url=validate_public_http_url(request.url),
            javascript=bool(request.javascript),
        )
        primary_error: CrawlerProviderError | None = None
        try:
            document = self._crawl4ai.crawl(safe_request, self.limits)
            return self._bounded(document)
        except CrawlerProviderError as exc:
            if exc.captcha:
                raise
            primary_error = exc

        try:
            document = self._scrapling.crawl(safe_request, self.limits)
            return self._bounded(document)
        except CrawlerProviderError as exc:
            if str(exc) == "content_limit_exceeded":
                raise
            raise CrawlerProviderError(
                "all crawler providers failed",
                provider=CrawlerProvider.SCRAPLING,
                captcha=exc.captcha,
                retryable=bool(primary_error and primary_error.retryable and exc.retryable),
            ) from None

    def _bounded(self, document: CrawlerDocument) -> CrawlerDocument:
        content_size = len(document.markdown.encode("utf-8"))
        if content_size > self.limits.max_content_bytes:
            raise CrawlerProviderError(
                "content_limit_exceeded",
                provider=document.provider,
            )
        validate_public_http_url(document.url)
        return document


class Crawl4AIProcessProvider:
    """Invoke the package-owned Crawl4AI runner through a fixed executable path."""

    provider = CrawlerProvider.CRAWL4AI

    def __init__(self, *, executable: Path, runner: ProcessRunner) -> None:
        self._executable = executable
        self._runner = runner

    def crawl(self, request: CrawlRequest, limits: CrawlLimits) -> CrawlerDocument:
        argv = [
            str(self._executable),
            "--url",
            request.url,
            "--timeout-seconds",
            str(limits.timeout_seconds),
            "--max-content-bytes",
            str(limits.max_content_bytes),
            "--redirect-limit",
            str(limits.redirect_limit),
            "--retry-limit",
            str(limits.retry_limit),
        ]
        if request.javascript:
            argv.append("--javascript")
        result = self._runner(argv, limits.timeout_seconds + 10)
        if result.returncode != 0:
            error_code = "crawl_failed"
            captcha = False
            try:
                error_payload = json.loads(result.stdout or result.stderr)
                if isinstance(error_payload, dict):
                    error_code = str(error_payload.get("error", error_code))
                    captcha = bool(error_payload.get("captcha", False))
            except json.JSONDecodeError:
                pass
            raise CrawlerProviderError(
                error_code,
                provider=self.provider,
                captcha=captcha,
                retryable=error_code in {"timeout", "network_failed"},
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CrawlerProviderError(
                "invalid_crawl4ai_response",
                provider=self.provider,
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            error_code = (
                str(payload.get("error", "crawl_failed"))
                if isinstance(payload, dict)
                else "crawl_failed"
            )
            captcha = (
                bool(payload.get("captcha", False)) if isinstance(payload, dict) else False
            )
            raise CrawlerProviderError(
                error_code,
                provider=self.provider,
                captcha=captcha,
            )
        return CrawlerDocument(
            title=str(payload.get("title", "")).strip(),
            url=validate_public_http_url(str(payload.get("url", request.url))),
            source=str(payload.get("source", "")).strip(),
            markdown=str(payload.get("markdown", "")),
            provider=self.provider,
            status_code=_optional_int(payload.get("status_code")),
        )


class ScraplingProvider:
    """Reuse the already-approved Scrapling MCP tools as a single fallback attempt."""

    provider = CrawlerProvider.SCRAPLING

    def __init__(self, *, runner: ProcessRunner) -> None:
        self._runner = runner

    def crawl(self, request: CrawlRequest, limits: CrawlLimits) -> CrawlerDocument:
        selector = "scrapling.fetch" if request.javascript else "scrapling.get"
        argv = [
            "mcporter",
            "call",
            selector,
            f"url={request.url}",
            "extraction_type=markdown",
            "main_content_only=true",
        ]
        result = self._runner(argv, limits.timeout_seconds)
        if result.returncode != 0:
            raise CrawlerProviderError(
                "scrapling_failed",
                provider=self.provider,
                retryable=True,
            )
        markdown = result.stdout.strip()
        if not markdown:
            raise CrawlerProviderError("empty_content", provider=self.provider)
        parsed = urlparse(request.url)
        title = _markdown_title(markdown) or parsed.hostname or request.url
        return CrawlerDocument(
            title=title,
            url=request.url,
            source=parsed.hostname or "",
            markdown=markdown,
            provider=self.provider,
            status_code=200,
        )


def build_installed_crawler_adapter(
    *,
    runner: ProcessRunner,
    root: Path | None = None,
    limits: CrawlLimits | None = None,
) -> CrawlerAdapter | None:
    """Bind only the package-owned Crawl4AI runner; never discover arbitrary executables."""

    install_root = root or (
        Path.home() / ".local" / "share" / "picotoopet" / "research" / "crawl4ai"
    )
    executable = install_root / "bin" / "picotoopet-crawl4ai-provider"
    if not executable.is_file():
        return None
    return CrawlerAdapter(
        crawl4ai=Crawl4AIProcessProvider(executable=executable, runner=runner),
        scrapling=ScraplingProvider(runner=runner),
        limits=limits,
    )


def render_search_envelope(
    *,
    query: str,
    search_output: str,
    documents: list[CrawlerDocument],
    maximum_bytes: int = 47_000,
) -> str:
    """Serialize enriched content inside the existing ResearchSearchResult.output string budget."""

    payload = {
        "schema_version": "1.0",
        "query": query,
        "search_output": _truncate_utf8(search_output, 8_000),
        "documents": [_document_payload(document) for document in documents],
    }
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(rendered.encode("utf-8")) <= maximum_bytes:
        return rendered

    remaining = max(0, maximum_bytes - 12_000)
    per_document = max(1_000, remaining // max(1, len(documents)))
    payload["documents"] = [
        {
            **_document_payload(document),
            "markdown": _truncate_utf8(document.markdown, per_document),
        }
        for document in documents
    ]
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _truncate_utf8(rendered, maximum_bytes)


def _document_payload(document: CrawlerDocument) -> dict[str, object]:
    return {
        "title": document.title,
        "url": document.url,
        "source": document.source,
        "markdown": document.markdown,
        "provider": document.provider.value,
        "status_code": document.status_code,
    }


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    suffix = "\n...[truncated]"
    budget = max(0, maximum_bytes - len(suffix.encode("utf-8")))
    clipped = encoded[:budget]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix[:maximum_bytes]


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _markdown_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""