"""Core-owned immutable storage for business packages, results and manual handoffs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

from picotoopet_core.config.paths import RuntimePaths

from .archive import ValidatedWorkPackage


class BusinessArtifactStore:
    """Never derives filesystem paths from untrusted producer path strings."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.paths.ensure()

    @staticmethod
    def _safe_uuid(value: str) -> str:
        return str(UUID(value))

    @staticmethod
    def _digest(value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("invalid sha256 digest")
        return value

    def staging_archive(self, upload_session_id: str) -> Path:
        safe = self._safe_uuid(upload_session_id)
        return self.paths.business_staging_dir / f"{safe}.zip.partial"

    def relative_to_root(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.root.resolve()).as_posix()

    def resolve_managed_relative(self, relative: str) -> Path:
        candidate = (self.paths.root / relative).resolve()
        candidate.relative_to(self.paths.root.resolve())
        return candidate

    def promote_package(self, validated: ValidatedWorkPackage) -> tuple[str, str]:
        package_id = self._safe_uuid(validated.manifest.package_id)
        digest = self._digest(validated.source_digest)
        destination_dir = self.paths.business_packages_dir / package_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{digest}.zip"
        if destination.exists():
            existing = self.sha256_file(destination)
            if existing != digest:
                raise ValueError("immutable package conflict")
        else:
            temporary = destination.with_suffix(".zip.partial")
            if temporary.exists():
                temporary.unlink()
            os.replace(validated.archive_path, temporary)
            os.replace(temporary, destination)
        return self.relative_to_root(destination), digest

    def open_package(self, relative: str) -> Path:
        path = self.resolve_managed_relative(relative)
        path.relative_to(self.paths.business_packages_dir.resolve())
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def write_result_package(
        self,
        *,
        result_package_id: str,
        payload: dict[str, object],
    ) -> tuple[str, str]:
        return self._write_json_zip(
            root=self.paths.business_results_dir,
            identity=result_package_id,
            member_name="result-package.json",
            payload=payload,
        )

    def write_handoff_package(
        self,
        *,
        handoff_id: str,
        payload: dict[str, object],
    ) -> tuple[str, str]:
        return self._write_json_zip(
            root=self.paths.business_handoffs_dir,
            identity=handoff_id,
            member_name="deep-ai-handoff.json",
            payload=payload,
        )

    def _write_json_zip(
        self,
        *,
        root: Path,
        identity: str,
        member_name: str,
        payload: dict[str, object],
    ) -> tuple[str, str]:
        safe_id = self._safe_uuid(identity)
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        root.mkdir(parents=True, exist_ok=True)
        final = root / f"{safe_id}.zip"
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
                    raise ValueError("immutable output conflict")
                temporary.unlink()
            else:
                os.replace(temporary, final)
        finally:
            if temporary.exists():
                temporary.unlink()
        return self.relative_to_root(final), self.sha256_file(final)

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
