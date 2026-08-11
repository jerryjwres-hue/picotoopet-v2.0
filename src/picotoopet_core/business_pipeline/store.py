"""Core-owned immutable storage for Business Return Package v1."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

from picotoopet_core.config.paths import RuntimePaths


class BusinessReturnPackageStore:
    """Store return packages under a fixed Core-owned business/returns root."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.root = self.paths.business_root / "returns"
        self.paths.ensure()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_uuid(value: str) -> str:
        return str(UUID(value))

    def relative_to_root(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.root.resolve()).as_posix()

    def resolve_managed_relative(self, relative: str) -> Path:
        candidate = (self.paths.root / relative).resolve()
        candidate.relative_to(self.paths.root.resolve())
        candidate.relative_to(self.root.resolve())
        return candidate

    def write_package(self, return_package_id: str, payload: dict[str, object]) -> tuple[str, str]:
        safe_id = self._safe_uuid(return_package_id)
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        final = self.root / f"{safe_id}.zip"
        with tempfile.NamedTemporaryFile(dir=self.root, suffix=".partial", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                info = zipfile.ZipInfo(f"{safe_id}/return-package.json")
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, encoded)
            digest = self.sha256_file(temporary)
            if final.exists():
                if self.sha256_file(final) != digest:
                    raise ValueError("PIPELINE_RETURN_PACKAGE_IMMUTABLE_CONFLICT")
                temporary.unlink()
            else:
                os.replace(temporary, final)
        finally:
            if temporary.exists():
                temporary.unlink()
        return self.relative_to_root(final), self.sha256_file(final)

    def open_package(self, relative: str) -> Path:
        candidate = self.resolve_managed_relative(relative)
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
