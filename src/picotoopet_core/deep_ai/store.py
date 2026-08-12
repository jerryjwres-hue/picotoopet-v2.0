"""Managed immutable storage for sanitized Deep-AI request packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from picotoopet_core.config.paths import RuntimePaths

from .sanitizer import DeepAiSanitizedPackage


@dataclass(frozen=True, slots=True)
class StoredDeepAiPackage:
    relpath: str
    digest: str
    size_bytes: int


class DeepAiSanitizedPackageStore:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.paths.deep_ai_requests_dir.mkdir(parents=True, exist_ok=True)

    def save(self, package: DeepAiSanitizedPackage) -> StoredDeepAiPackage:
        filename = f"{package.digest}.json"
        target = (self.paths.deep_ai_requests_dir / filename).resolve()
        root = self.paths.deep_ai_requests_dir.resolve()
        if target.parent != root:
            raise ValueError("DEEP_AI_PACKAGE_PATH_ESCAPE")
        if target.exists():
            current = target.read_bytes()
            if current != package.canonical_bytes:
                raise ValueError("DEEP_AI_PACKAGE_DIGEST_CONFLICT")
        else:
            temporary = target.with_suffix(".json.tmp")
            temporary.write_bytes(package.canonical_bytes)
            temporary.replace(target)
        relpath = target.relative_to(self.paths.root.resolve()).as_posix()
        return StoredDeepAiPackage(
            relpath=relpath,
            digest=package.digest,
            size_bytes=len(package.canonical_bytes),
        )

    def read(self, relpath: str) -> bytes:
        root = self.paths.root.resolve()
        target = (root / Path(relpath)).resolve()
        request_root = self.paths.deep_ai_requests_dir.resolve()
        if target.parent != request_root:
            raise ValueError("DEEP_AI_PACKAGE_PATH_ESCAPE")
        return target.read_bytes()
