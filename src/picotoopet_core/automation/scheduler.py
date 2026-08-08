"""Small scheduler facade for restart-safe workflow reconciliation."""

from __future__ import annotations

from .models import WorkflowRecord
from .service import WorkflowService


class WorkflowScheduler:
    """Run bounded reconciliation passes; execution remains in registered Workers."""

    def __init__(self, service: WorkflowService) -> None:
        self.service = service

    def reconcile_all(self, *, limit: int = 200) -> list[WorkflowRecord]:
        workflows = self.service.list_workflows(limit=limit)
        return [self.service.reconcile(item.workflow_id) for item in workflows]
