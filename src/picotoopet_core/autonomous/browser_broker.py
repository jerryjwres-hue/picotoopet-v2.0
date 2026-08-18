"""Read-only public-page Browser Broker contract migrated from Maotai OS 4.1."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

DEFAULT_EXTENSION_ID = "miagfkomnofgeeahbficblhlcgahaldp"
_MAX_PAYLOAD_BYTES = 480 * 1024
_MAX_PUBLIC_SIGNALS = 50
_MAX_SIGNAL_TEXT_CHARS = 5_000
_EVIDENCE_MESSAGE_TYPES = {
    "capture_product",
    "capture_page",
    "capture_visible_signals",
    "send_to_current_product",
    "capture_batch_v4",
}
_NON_EVIDENCE_MESSAGE_TYPES = {"ping", "capture_complete_v4"}
_FORBIDDEN_KEYS = {
    "cookie",
    "cookies",
    "authorization",
    "auth",
    "token",
    "accesstoken",
    "refreshtoken",
    "password",
    "payment",
    "creditcard",
    "localstorage",
    "sessionstorage",
    "sessiontoken",
}
_KEY_NORMALIZER = re.compile(r"[^a-z0-9]")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_INTEGER_RE = re.compile(r"\d+")


class BrowserCaptureEvidence(BaseModel):
    """Sanitized public evidence; this object has no persistence or browser-control powers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    message_type: str
    source_url: str
    domain: str
    platform: str
    title: str
    observations: dict[str, int | float]
    public_signals: list[dict[str, object]]


def validate_browser_capture(
    packet: dict[str, object],
    *,
    allowed_extension_id: str | None = None,
) -> BrowserCaptureEvidence:
    """Validate and sanitize one legacy capture packet without persisting or controlling a browser."""

    if not isinstance(packet, dict):
        raise ValueError("capture must be a JSON object")

    raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(raw.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("capture payload exceeds safe size limit")
    if _contains_forbidden_key(packet):
        raise ValueError("capture payload contains forbidden secret/session fields")

    message_type = str(packet.get("type") or "").strip()
    if message_type in _NON_EVIDENCE_MESSAGE_TYPES:
        raise ValueError("message type is not evidence-bearing")
    if message_type not in _EVIDENCE_MESSAGE_TYPES:
        raise ValueError("unsupported bridge message type")

    expected_extension = allowed_extension_id or DEFAULT_EXTENSION_ID
    extension_id = str(packet.get("extension_id") or "").strip()
    if extension_id and extension_id != expected_extension:
        raise ValueError("extension id is not allowed")

    source_url, domain = _public_url(str(packet.get("url") or ""))
    page_value = packet.get("page")
    if page_value is None:
        page: dict[str, object] = {}
    elif isinstance(page_value, dict):
        page = page_value
    else:
        raise ValueError("page must be an object")

    title = _first_text(page, "product_title", "title")
    observations = _public_observations(page)
    public_signals = _public_signals(page)
    platform = _platform_for_domain(domain)

    stable = {
        "message_type": message_type,
        "source_url": source_url,
        "domain": domain,
        "platform": platform,
        "title": title,
        "observations": observations,
        "public_signals": public_signals,
    }
    digest = hashlib.sha256(
        json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return BrowserCaptureEvidence(
        evidence_id=f"browser-{digest}",
        message_type=message_type,
        source_url=source_url,
        domain=domain,
        platform=platform,
        title=title,
        observations=observations,
        public_signals=public_signals,
    )


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _KEY_NORMALIZER.sub("", str(key).casefold())
            if normalized in _FORBIDDEN_KEYS or _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _public_url(value: str) -> tuple[str, str]:
    source_url = value.strip()
    parsed = urlsplit(source_url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("capture URL must be a public http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credential-bearing capture URLs are forbidden")

    domain = parsed.hostname.casefold().rstrip(".")
    if domain == "localhost" or domain.endswith(".localhost"):
        raise ValueError("non-public capture URL is forbidden")
    try:
        address = ipaddress.ip_address(domain)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("non-public capture URL is forbidden")
    return source_url, domain


def _platform_for_domain(domain: str) -> str:
    bare = domain.removeprefix("www.")
    if bare == "amazon.com" or bare.startswith("amazon.") or ".amazon." in bare:
        return "amazon"
    if bare == "tiktok.com" or bare.endswith(".tiktok.com") or "tiktokshop.com" in bare:
        return "tiktok"
    return "web"


def _first_text(page: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = page.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text[:1_000]
    return ""


def _public_observations(page: dict[str, object]) -> dict[str, int | float]:
    observations: dict[str, int | float] = {}
    rating = _float_value(page.get("rating"))
    if rating is not None:
        observations["rating"] = rating
    review_count = _int_value(page.get("review_count"))
    if review_count is not None:
        observations["review_count"] = review_count
    for key in ("sold_count", "like_count", "comment_count", "share_count"):
        count = _compact_int(page.get(key))
        if count is not None:
            observations[key] = count
    price = _float_value(page.get("price"))
    if price is not None:
        observations["price"] = price
    return observations


def _public_signals(page: dict[str, object]) -> list[dict[str, object]]:
    value = page.get("visible_signals")
    if not isinstance(value, list):
        return []
    sanitized: list[dict[str, object]] = []
    for item in value[:_MAX_PUBLIC_SIGNALS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:_MAX_SIGNAL_TEXT_CHARS]
        if not text:
            continue
        output: dict[str, object] = {"text": text}
        rating = _float_value(item.get("rating"))
        if rating is not None:
            output["rating"] = rating
        for key, maximum in (
            ("source_id", 200),
            ("stable_key", 12_000),
            ("title", 1_000),
            ("date", 1_000),
            ("author", 500),
            ("source_url", 4_000),
            ("signal_kind", 100),
        ):
            text_value = str(item.get(key) or "").strip()
            if text_value:
                output[key] = text_value[:maximum]
        verified = item.get("verified")
        if verified is not None:
            output["verified"] = _bool_value(verified)
        sanitized.append(output)
    return sanitized


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value or "").replace(",", ""))
    return float(match.group(0)) if match else None


def _int_value(value: object) -> int | None:
    match = _INTEGER_RE.search(str(value or "").replace(",", ""))
    return int(match.group(0)) if match else None


def _compact_int(value: object) -> int | None:
    raw = str(value or "").replace(",", "").strip()
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([KMB])?", raw, re.IGNORECASE)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        str(match.group(2) or "").upper()
    ]
    return int(round(float(match.group(1)) * multiplier))


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "verified",
        "verified purchase",
    }
