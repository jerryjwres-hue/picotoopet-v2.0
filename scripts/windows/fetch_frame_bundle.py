"""Fetch a one-use Mac Core frame ZIP over an authenticated secure channel.

This is an internal CPU-only adapter to the existing stage_frame_bundle()
consumer. It never calls Comfy, the GPU queue or a production admission API.
"""

from __future__ import annotations

import hashlib
import ipaddress
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests

try:
    from .stage_frame_bundle import FrameStageError, stage_frame_bundle
except ImportError:
    from stage_frame_bundle import FrameStageError, stage_frame_bundle

_MAX_DOWNLOAD_BYTES = 129 * 1024 * 1024
_CHUNK = 1024 * 1024


class FrameFetchError(ValueError):
    """Stable error codes; never display the ticket or device credentials."""


def _secure_core_url(core_url: str) -> str:
    """Forbid remote plaintext HTTP, credentials in URL and arbitrary URL parts."""
    try:
        parsed = urlsplit(core_url)
        host = parsed.hostname or ""
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if (
        parsed.scheme not in ("https", "http")
        or (parsed.scheme != "https" and not loopback)
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
    ):
        raise FrameFetchError("FRAME_FETCH_SECURE_CORE_URL_REQUIRED")
    return core_url.rstrip("/")


def fetch_and_stage_frame_bundle(
    *,
    session: requests.Session,
    core_url: str,
    transfer_ticket: str,
    expected_source_bindings_sha256: str,
    expected_bundle_sha256: str,
    worker_root: Path,
) -> dict:
    """Authenticated one-use HTTP download, ZIP SHA and Windows-local file SHA."""
    if not (
        isinstance(transfer_ticket, str)
        and 20 <= len(transfer_ticket) <= 160
        and isinstance(expected_source_bindings_sha256, str)
        and len(expected_source_bindings_sha256) == 64
        and isinstance(expected_bundle_sha256, str)
        and len(expected_bundle_sha256) == 64
        and all(char in "0123456789abcdef" for char in expected_source_bindings_sha256)
        and all(char in "0123456789abcdef" for char in expected_bundle_sha256)
    ):
        raise FrameFetchError("FRAME_FETCH_INPUT_INVALID")
    url = _secure_core_url(core_url) + "/api/v1/studio/frame-transfer/download"

    # 不从响应正文或返回头自选正确 SHA；预期值必须来自可信 Core/Owner 会话。
    try:
        with tempfile.TemporaryDirectory(prefix="picotoo-frame-download-") as folder:
            destination = Path(folder) / "frames.zip"
            with session.get(
                url,
                headers={
                    "X-Picotoo-Transfer-Ticket": transfer_ticket,
                    "Accept": "application/zip",
                },
                stream=True, timeout=(4, 90), allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise FrameFetchError("FRAME_FETCH_NOT_AUTHORIZED_OR_STALE")
                if response.headers.get("Content-Type", "").split(";")[0] != "application/zip":
                    raise FrameFetchError("FRAME_FETCH_TYPE_INVALID")
                if (
                    response.headers.get("X-Picotoo-Source-Bindings-Sha256")
                    != expected_source_bindings_sha256
                    or response.headers.get("X-Picotoo-Bundle-Sha256")
                    != expected_bundle_sha256
                ):
                    raise FrameFetchError("FRAME_FETCH_RESPONSE_SHA_MISMATCH")
                hasher = hashlib.sha256()
                count = 0
                with destination.open("xb") as output:
                    for chunk in response.iter_content(chunk_size=_CHUNK):
                        if not chunk:
                            continue
                        count += len(chunk)
                        if count > _MAX_DOWNLOAD_BYTES:
                            raise FrameFetchError("FRAME_FETCH_TOO_LARGE")
                        output.write(chunk)
                        hasher.update(chunk)
                if count == 0 or hasher.hexdigest() != expected_bundle_sha256:
                    raise FrameFetchError("FRAME_FETCH_ZIP_SHA_MISMATCH")
            receipt = stage_frame_bundle(
                destination,
                expected_source_bindings_sha256=expected_source_bindings_sha256,
                worker_root=worker_root,
            )
            # 二次验证由现有阶段完成；此回执仍不签发生产任务或 GPU 权限。
            if receipt["worker_local_bytes_verified"] is not True:
                raise FrameFetchError("FRAME_FETCH_WORKER_STAGING_FAILED")
            return receipt
    except (requests.RequestException, OSError, FrameStageError) as error:
        raise FrameFetchError("FRAME_FETCH_TRANSPORT_OR_STAGING_FAILED") from error
