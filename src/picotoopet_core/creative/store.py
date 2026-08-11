"""Core-managed immutable storage for Creative Packages and manual handoffs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from picotoopet_core.config.paths import RuntimePaths


class CreativeArtifactStore:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.paths.ensure()

    @staticmethod
    def _safe_uuid(value: str) -> str:
        return str(UUID(value))

    def resolve_managed_relative(self, relative: str) -> Path:
        candidate = (self.paths.root / relative).resolve()
        candidate.relative_to(self.paths.root.resolve())
        return candidate

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.root.resolve()).as_posix()

    def write_creative_package(
        self,
        creative_package_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        return self._write_json_zip(
            root=self.paths.creative_packages_dir,
            identity=creative_package_id,
            member_name="creative-package.json",
            payload=payload,
        )

    def write_handoff_package(
        self,
        handoff_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        return self._write_json_zip(
            root=self.paths.creative_handoffs_dir,
            identity=handoff_id,
            member_name="creative-deep-ai-handoff.json",
            payload=self._sanitize(payload),
        )

    def _write_json_zip(
        self,
        *,
        root: Path,
        identity: str,
        member_name: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        safe_id = self._safe_uuid(identity)
        root.mkdir(parents=True, exist_ok=True)
        final = root / f"{safe_id}.zip"
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=root, suffix=".partial", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                info = zipfile.ZipInfo(f"{safe_id}/{member_name}")
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, encoded)
            digest = self.sha256_file(temporary)
            if final.exists():
                if self.sha256_file(final) != digest:
                    raise ValueError("immutable creative output conflict")
                temporary.unlink()
            else:
                os.replace(temporary, final)
            return self._relative(final), self.sha256_file(final)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in list(value.items())[:80]:
                lowered = str(key).lower()
                if any(marker in lowered for marker in ("token", "password", "secret", "authorization", "cookie", "path")):
                    result[str(key)] = "***REDACTED***"
                else:
                    result[str(key)] = cls._sanitize(item)
            return result
        if isinstance(value, list):
            return [cls._sanitize(item) for item in value[:80]]
        if isinstance(value, str):
            lowered = value.lower()
            if value.startswith("/Users/") or lowered.startswith("c:\\users\\"):
                return "***REDACTED_PATH***"
            return value[:4000]
        return value

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
