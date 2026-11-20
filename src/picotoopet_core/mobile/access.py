"""Ephemeral, read-only mobile pairing: never deliver Core device tokens to phones."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time


class MobileAccess:
    """App-local pairing and browser sessions; restart invalidates every session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pair_hash: str | None = None
        self._pair_until = 0.0
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, tuple[int, float]] = {}

    @staticmethod
    def _digest(value: str) -> str:
        # 内存只保留摘要，不把手机 Cookie、配对码或设备 Token 写进 SQLite。
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def issue_pairing(self) -> dict:
        """Issue one short-lived code to an already authenticated Core device."""
        code = secrets.token_hex(5).upper()            # 40-bit 单次配对，5 分钟后失效。
        with self._lock:
            self._pair_hash = self._digest(code)
            self._pair_until = time.monotonic() + 300
            self._failures.clear()
        return {"code": code, "expires_seconds": 300, "read_only": True}

    def claim(self, code: str, source: str) -> str | None:
        """Rate-limit guessing and atomically consume one code on successful pairing."""
        with self._lock:
            now = time.monotonic()
            tries, reset_at = self._failures.get(source, (0, now + 300))
            if now > reset_at:
                tries, reset_at = 0, now + 300
            if tries >= 5:
                return None
            self._failures[source] = (tries + 1, reset_at)
            if (
                self._pair_hash is None
                or now >= self._pair_until
                or not hmac.compare_digest(self._digest(code.strip().upper()), self._pair_hash)
            ):
                return None
            self._pair_hash = None                  # 使用一次即废止，防止旁人再次绑定。
            self._pair_until = 0.0
            self._failures.pop(source, None)
            secret = secrets.token_urlsafe(32)
            self._sessions[self._digest(secret)] = now + 8 * 3600
            if len(self._sessions) > 16:
                self._sessions = {
                    k: until for k, until in self._sessions.items() if until > now
                }
            return secret

    def valid(self, secret: str | None) -> bool:
        if not secret:
            return False
        with self._lock:
            now = time.monotonic()
            digest = self._digest(secret)
            until = self._sessions.get(digest, 0)
            if until <= now:
                self._sessions.pop(digest, None)
                return False
            return True

    def revoke(self, secret: str | None) -> None:
        if secret:
            with self._lock:
                self._sessions.pop(self._digest(secret), None)
