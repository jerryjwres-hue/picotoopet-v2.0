"""Digest-bound generalized Handoff/Return workflow continuation."""

from __future__ import annotations

from .models import WorkflowContinuationCreate
from .repository import AutomationRepository


class WorkflowContinuationService:
    """Bind existing Handoff/Return facts to an exact workflow checkpoint."""

    def __init__(self, repository: AutomationRepository) -> None:
        self.repository = repository

    def prepare(self, request: WorkflowContinuationCreate) -> str:
        return self.repository.create_continuation(request)

    def bind_return(
        self,
        *,
        handoff_id: str,
        return_id: str,
        checkpoint_digest: str,
    ) -> None:
        self.repository.bind_return(handoff_id, return_id, checkpoint_digest)
