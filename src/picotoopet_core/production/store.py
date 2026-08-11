"""Core-managed immutable storage for Production Package v1."""

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


class ProductionArtifactStore:
    def __init__(self, paths: RuntimePaths) -> None:
        # ── Storage remains under the Mac Core managed root ─────────────────
        self.paths = paths
        self.paths.ensure()

    def resolve_managed_relative(self, relative: str) -> Path:
        # ── A stored relative path may never escape the managed root ────────
        candidate = (self.paths.root / relative).resolve()
        candidate.relative_to(self.paths.root.resolve())
        return candidate

    def write_package(self, production_package_id: str, payload: dict[str, Any]) -> tuple[str, str]:
        # ── Immutable single-member ZIP mirrors prior business/creative stores ─
        safe_id = str(UUID(production_package_id))
        root = self.paths.production_packages_dir
        root.mkdir(parents=True, exist_ok=True)
        final = root / f"{safe_id}.zip"
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=root, suffix=".partial", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                info = zipfile.ZipInfo(f"{safe_id}/production-package.json")
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, encoded)
            digest = self.sha256_file(temporary)
            if final.exists():
                if self.sha256_file(final) != digest:
                    raise ValueError("immutable production output conflict")
                temporary.unlink()
            else:
                os.replace(temporary, final)
            relative = final.resolve().relative_to(self.paths.root.resolve()).as_posix()
            return relative, self.sha256_file(final)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def sha256_file(path: Path) -> str:
        # ── Content addressing always uses SHA-256 ──────────────────────────
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
