"""Artifact provenance metadata without user-directory enumeration."""

from __future__ import annotations

from .models import ArtifactProvenanceCreate
from .repository import AutomationRepository


class ArtifactProvenanceService:
    """Attach immutable SHA-256 provenance to an already-known artifact ID."""

    def __init__(self, repository: AutomationRepository) -> None:
        self.repository = repository

    def record(self, request: ArtifactProvenanceCreate) -> None:
        self.repository.record_artifact_provenance(request)
