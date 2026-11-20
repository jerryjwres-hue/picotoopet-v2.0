"""Ephemeral, Owner-issued, one-use frame ZIP transfer tickets.

Tokens are capabilities for *data delivery only*. They never grant
MASTER rights, queue creation, a GPU lease, or a Production Plan.
"""

from __future__ import annotations

import hashlib
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_MAX_ACTIVE = 1
_TTL_SECONDS = 120


class FrameTransferError(ValueError):
    """A stable fail-closed reason with no credential or local path details."""


@dataclass(frozen=True)
class _Ticket:
    path: Path
    manifest_sha256: str
    bundle_sha256: str
    expires_at: float
    validate_current: Callable[[], None]


class FrameTransferTickets:
    """Process-bound, one-time tickets; no extra DB, scheduler or API secret."""

    def __init__(self) -> None:
        # 系统私有临时目录             不放进正式素材库或对外静态目录。
        self._folder = tempfile.TemporaryDirectory(prefix="picotoo-frame-transfer-")
        self._lock = threading.RLock()
        self._active: dict[str, _Ticket] = {}
        self._closed = False

    def _purge_expired(self) -> None:
        # 本方法只能在持锁状态调用；没有后台定时器。
        now = time.monotonic()
        for key, item in tuple(self._active.items()):
            if item.expires_at <= now:
                self._active.pop(key)
                item.path.unlink(missing_ok=True)

    def issue(
        self,
        *,
        manifest_sha256: str,
        export: Callable[[Path], dict],
        validate_current: Callable[[], None],
    ) -> dict:
        """Export one already verified bundle and issue an ephemeral token."""
        with self._lock:
            if self._closed:
                raise FrameTransferError("FRAME_TRANSFER_CLOSED")
            self._purge_expired()
            if len(self._active) >= _MAX_ACTIVE:
                raise FrameTransferError("FRAME_TRANSFER_BUSY")
            token = secrets.token_urlsafe(32)
            key = hashlib.sha256(token.encode("ascii")).hexdigest()
            path = Path(self._folder.name) / f"{key}.zip"
            try:
                # 传输前再次验证审批与源摘要；失败不留下可下载 ZIP。
                validate_current()
                result = export(path)
                validate_current()
                if result["source_bindings_sha256"] != manifest_sha256:
                    raise FrameTransferError("FRAME_TRANSFER_SOURCE_CHANGED")
                bundle_digest = result["bundle_sha256"]
            except BaseException:
                path.unlink(missing_ok=True)
                raise

            self._active[key] = _Ticket(
                path=path,
                manifest_sha256=manifest_sha256,
                bundle_sha256=bundle_digest,
                expires_at=time.monotonic() + _TTL_SECONDS,
                validate_current=validate_current,
            )
            return {
                "status": "FRAME_TRANSFER_TICKET_ISSUED_DATA_ONLY",
                "ticket": token,
                "source_bindings_sha256": manifest_sha256,
                "bundle_sha256": bundle_digest,
                "expires_in_seconds": _TTL_SECONDS,
                "single_use": True,
                "can_queue": False,
                "gpu_authorized": False,
            }

    def consume(self, token: str) -> _Ticket:
        """Consume before serving. Revocation/byte drift is rechecked on use."""
        if not isinstance(token, str) or not 20 <= len(token) <= 160:
            raise FrameTransferError("FRAME_TRANSFER_TOKEN_INVALID")
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            if self._closed:
                raise FrameTransferError("FRAME_TRANSFER_CLOSED")
            self._purge_expired()
            item = self._active.pop(key, None)
            if item is None:
                raise FrameTransferError("FRAME_TRANSFER_NOT_FOUND_OR_USED")
            try:
                item.validate_current()
            except BaseException as error:
                item.path.unlink(missing_ok=True)
                raise FrameTransferError("FRAME_TRANSFER_SOURCE_OR_APPROVAL_STALE") from error
            return item

    def finish(self, path: Path) -> None:
        """Remove staged private bytes after file transfer completes or aborts."""
        with self._lock:
            path.unlink(missing_ok=True)

    def close(self) -> None:
        """Invalidate all outstanding tickets and remove the private tempdir."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active.clear()
            self._folder.cleanup()
