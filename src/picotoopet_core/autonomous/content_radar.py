"""Deterministic Content Radar primitives; models never invent missing research facts."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref_src",
}
_WHITESPACE_RE = re.compile(r"\s+")


class RadarCandidateInput(BaseModel):
    """One bounded evidence-backed item entering deterministic Radar processing."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    evidence_id: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=4096)
    title: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=8_000)
    platform: str | None = Field(default=None, max_length=80)

    @field_validator("evidence_id", "url", "title", "excerpt")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()


class RadarCandidate(BaseModel):
    """Normalized immutable candidate with stable provenance and identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    canonical_url: str
    domain: str
    title: str
    excerpt: str
    platform: str | None = None
    evidence_ids: list[str]


def normalize_candidates(inputs: list[RadarCandidateInput]) -> list[RadarCandidate]:
    """Normalize URLs/text and collapse exact URL/content duplicates deterministically."""

    if len(inputs) > 500:
        raise ValueError("too many radar candidates")
    if not inputs:
        return []

    prepared: list[tuple[RadarCandidateInput, str, str, str]] = []
    for item in inputs:
        canonical_url, domain = _canonical_public_url(item.url)
        content_key = _content_key(item.title, item.excerpt)
        prepared.append((item, canonical_url, domain, content_key))

    # Union-find is used instead of one-pass dictionaries so duplicate relations
    # are transitive: same URL can connect two exact-text duplicate source pages.
    parents = list(range(len(prepared)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parents[right_root] = left_root
        else:
            parents[left_root] = right_root

    by_url: dict[str, int] = {}
    by_content: dict[str, int] = {}
    for index, (_, canonical_url, _, content_key) in enumerate(prepared):
        prior_url = by_url.setdefault(canonical_url, index)
        union(index, prior_url)
        prior_content = by_content.setdefault(content_key, index)
        union(index, prior_content)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(prepared)):
        groups[find(index)].append(index)

    normalized: list[RadarCandidate] = []
    for member_indexes in groups.values():
        members = [prepared[index] for index in member_indexes]
        # Choose the representative by normalized URL, then normalized content,
        # making the output independent from caller input order.
        representative = min(
            members,
            key=lambda entry: (
                entry[1],
                entry[3],
                entry[0].evidence_id,
            ),
        )
        item, canonical_url, domain, content_key = representative
        evidence_ids = sorted({entry[0].evidence_id for entry in members})
        platforms = sorted(
            {
                entry[0].platform.strip()
                for entry in members
                if isinstance(entry[0].platform, str) and entry[0].platform.strip()
            }
        )
        normalized.append(
            RadarCandidate(
                candidate_id=_candidate_id(canonical_url, content_key),
                canonical_url=canonical_url,
                domain=domain,
                title=_display_text(item.title),
                excerpt=_display_text(item.excerpt),
                platform=platforms[0] if platforms else None,
                evidence_ids=evidence_ids,
            )
        )

    return sorted(normalized, key=lambda item: (item.canonical_url, item.candidate_id))


def _canonical_public_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be a public http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credential-bearing URLs are forbidden")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("non-public URL is forbidden")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("non-public URL is forbidden")

    scheme = parsed.scheme.lower()
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    query_pairs = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    path = parsed.path or "/"
    canonical = urlunsplit((scheme, netloc, path, query, ""))
    return canonical, hostname


def _display_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip())


def _content_key(title: str, excerpt: str) -> str:
    return f"{_display_text(title).casefold()}\n{_display_text(excerpt).casefold()}"


def _candidate_id(canonical_url: str, content_key: str) -> str:
    digest = hashlib.sha256(f"{canonical_url}\n{content_key}".encode("utf-8")).hexdigest()[:20]
    return f"radar-{digest}"
