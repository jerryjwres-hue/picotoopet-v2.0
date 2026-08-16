"""Package-owned Crawl4AI runner with read-only browser and network safety gates."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

_CAPTCHA_MARKERS = (
    "captcha",
    "verify you are human",
    "verification required",
    "cloudflare challenge",
    "turnstile",
)
_NOT_FOUND_MARKERS = ("404", "not found")
_TIMEOUT_MARKERS = ("timeout", "timed out")
_NETWORK_MARKERS = ("net::err_", "connection", "network")


def _validate_public_url(url: str) -> str:
    """Validate a browser destination before any network request is allowed."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("non_public_destination")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credential_bearing_url")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("non_public_destination")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("non_public_destination")
    return url


def _host_resolves_public(hostname: str) -> bool:
    """Reject DNS answers containing any non-global address to reduce SSRF/rebinding risk."""

    try:
        answers = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    addresses = {item[4][0] for item in answers if item and item[4]}
    if not addresses:
        return False
    for value in addresses:
        try:
            if not ipaddress.ip_address(value).is_global:
                return False
        except ValueError:
            return False
    return True


def _markdown_text(markdown: object) -> str:
    """Normalize Crawl4AI's MarkdownGenerationResult across compatible 0.9.x releases."""

    fit = getattr(markdown, "fit_markdown", None)
    if isinstance(fit, str) and fit.strip():
        return fit.strip()
    raw = getattr(markdown, "raw_markdown", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(markdown, str):
        return markdown.strip()
    return str(markdown or "").strip()


def _error_payload(code: str, *, captcha: bool = False) -> dict[str, object]:
    """Return a deliberately small error envelope without provider stderr or secrets."""

    return {"ok": False, "error": code, "captcha": captcha}


def _classify_provider_failure(error_message: str) -> str:
    """Classify only the bounded read failure categories exposed to Research Gateway."""

    lowered = error_message.lower()
    # Crawl4AI 0.9.x 的异常包装路径可能丢失 status_code；只在失败 error_message 中恢复明确 404。
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return "timeout"
    if any(marker in lowered for marker in _NETWORK_MARKERS):
        return "network_failed"
    return "crawl_failed"


def _effective_status_code(result_status: object, observed_status: int | None) -> int | None:
    """Prefer Crawl4AI status, falling back to the main Playwright navigation response."""

    if isinstance(result_status, int) and 100 <= result_status <= 599:
        return result_status
    if isinstance(observed_status, int) and 100 <= observed_status <= 599:
        return observed_status
    return None


async def _crawl_once(args: argparse.Namespace) -> dict[str, object]:
    """Run one Crawl4AI page read using an ephemeral Chromium context."""

    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

    requested_url = _validate_public_url(args.url)
    requested_host = urlparse(requested_url).hostname or ""
    if not await asyncio.to_thread(_host_resolves_public, requested_host):
        return _error_payload("network_failed")

    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False,
        use_persistent_context=False,
        accept_downloads=False,
    )
    strategy = AsyncPlaywrightCrawlerStrategy(browser_config=browser_config)
    host_cache: dict[str, bool] = {requested_host: True}
    observed_status: int | None = None

    async def guard_route(route: object, request: object) -> None:
        # Egress gate：页面内子请求与 HTTP redirect 都不能访问本机、私网或元数据地址。
        request_url = str(getattr(request, "url", ""))
        try:
            _validate_public_url(request_url)
            host = urlparse(request_url).hostname or ""
            allowed = host_cache.get(host)
            if allowed is None:
                allowed = await asyncio.to_thread(_host_resolves_public, host)
                host_cache[host] = allowed
            if not allowed:
                await route.abort()
                return
        except ValueError:
            await route.abort()
            return
        await route.continue_()

    async def on_page_context_created(page: object, context: object, **_: object) -> object:
        # 独立 context：只安装固定网络拦截器，不注入登录、cookie、token 或 stealth 脚本。
        await context.route("http://**/*", guard_route)
        await context.route("https://**/*", guard_route)
        return page

    async def after_goto(
        page: object,
        context: object,
        *,
        response: object | None = None,
        **_: object,
    ) -> object:
        # 主导航状态由受控 Playwright response 只读记录。
        # 仅用于补足 Crawl4AI 0.9.x 可能缺失的 status_code。
        nonlocal observed_status
        response_status = getattr(response, "status", None) if response is not None else None
        if isinstance(response_status, int):
            observed_status = response_status

        # Redirect gate：显式追溯 Playwright redirect chain，超过上限立即受控失败。
        redirect_count = 0
        current = getattr(response, "request", None) if response is not None else None
        while current is not None:
            current_url = str(getattr(current, "url", ""))
            _validate_public_url(current_url)
            previous = getattr(current, "redirected_from", None)
            if previous is None:
                break
            redirect_count += 1
            if redirect_count > args.redirect_limit:
                raise RuntimeError("redirect_limit_exceeded")
            current = previous
        return page

    strategy.set_hook("on_page_context_created", on_page_context_created)
    strategy.set_hook("after_goto", after_goto)

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=args.timeout_seconds * 1000,
        check_robots_txt=True,
        stream=False,
        wait_until="domcontentloaded",
        delay_before_return_html=0.75 if args.javascript else 0.15,
        scan_full_page=False,
        process_iframes=False,
        remove_forms=True,
    )
    data_root = Path(
        os.environ.get(
            "PICOTOOPET_CRAWL4AI_DATA_ROOT",
            str(Path.home() / ".local" / "share" / "picotoopet" / "research" / "crawl4ai" / "data"),
        )
    )
    data_root.mkdir(parents=True, exist_ok=True)

    async with AsyncWebCrawler(
        config=browser_config,
        crawler_strategy=strategy,
        base_directory=str(data_root),
    ) as crawler:
        result = await asyncio.wait_for(
            crawler.arun(url=requested_url, config=run_config),
            timeout=args.timeout_seconds + 5,
        )

    status_code = _effective_status_code(getattr(result, "status_code", None), observed_status)
    redirected_url = str(getattr(result, "redirected_url", "") or requested_url)
    try:
        _validate_public_url(redirected_url)
    except ValueError:
        return _error_payload("non_public_redirect")
    final_host = urlparse(redirected_url).hostname or ""
    if not await asyncio.to_thread(_host_resolves_public, final_host):
        return _error_payload("non_public_redirect")

    markdown = _markdown_text(getattr(result, "markdown", ""))
    metadata_payload = getattr(result, "metadata", {})
    title = ""
    if isinstance(metadata_payload, dict):
        title = str(metadata_payload.get("title", "")).strip()
    success = bool(getattr(result, "success", False))
    error_message = str(getattr(result, "error_message", "") or "")
    challenge_text = f"{title}\n{markdown[:4096]}\n{error_message}".lower()
    captcha = any(marker in challenge_text for marker in _CAPTCHA_MARKERS)

    if captcha and status_code in {401, 403, 429, None}:
        return _error_payload("captcha_required", captcha=True)
    if status_code == 404:
        return _error_payload("not_found")
    if status_code == 403 and not success:
        return _error_payload("robots_or_access_denied")
    if not success:
        return _error_payload(_classify_provider_failure(error_message))
    if not markdown:
        return _error_payload("empty_content")
    if len(markdown.encode("utf-8")) > args.max_content_bytes:
        return _error_payload("content_limit_exceeded")

    return {
        "ok": True,
        "title": title or final_host,
        "url": redirected_url,
        "source": final_host,
        "markdown": markdown,
        "status_code": status_code,
    }


async def _run_with_retries(args: argparse.Namespace) -> dict[str, object]:
    """Retry only transient failures and never exceed the explicit retry_limit."""

    attempts = args.retry_limit + 1
    last = _error_payload("crawl_failed")
    for attempt in range(attempts):
        try:
            last = await _crawl_once(args)
        except TimeoutError:
            last = _error_payload("timeout")
        except (OSError, RuntimeError, ValueError) as exc:
            code = str(exc) if str(exc) in {"redirect_limit_exceeded"} else "network_failed"
            last = _error_payload(code)
        if last.get("ok") is True:
            return last
        if bool(last.get("captcha", False)):
            return last
        if str(last.get("error")) not in {"timeout", "network_failed"}:
            return last
        if attempt + 1 < attempts:
            await asyncio.sleep(0.25)
    return last


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="picotoopet-crawl4ai-provider")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--javascript", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-content-bytes", type=int, default=262_144)
    parser.add_argument("--redirect-limit", type=int, default=5)
    parser.add_argument("--retry-limit", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        # 延迟导入仅用于版本查询，避免顶层 import 排序歧义；不触发 Crawl4AI 浏览器初始化。
        from importlib import metadata

        print(metadata.version("crawl4ai"))
        return 0
    if not args.url:
        print(json.dumps(_error_payload("url_required"), sort_keys=True))
        return 2
    if not 1 <= args.timeout_seconds <= 60:
        print(json.dumps(_error_payload("invalid_timeout"), sort_keys=True))
        return 2
    if not 1_024 <= args.max_content_bytes <= 1_048_576:
        print(json.dumps(_error_payload("invalid_content_limit"), sort_keys=True))
        return 2
    if not 0 <= args.redirect_limit <= 10 or not 0 <= args.retry_limit <= 2:
        print(json.dumps(_error_payload("invalid_retry_or_redirect_limit"), sort_keys=True))
        return 2

    payload = asyncio.run(_run_with_retries(args))
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
