"""Bounded restart-safe scheduler for end-to-end business pipeline reconciliation."""

from __future__ import annotations

import logging

from .models import BusinessPipelineRunRecord
from .service import BusinessPipelineService

logger = logging.getLogger(__name__)


class BusinessPipelineScheduler:
    """Reconcile durable pipeline runs while isolating failures per run."""

    def __init__(self, service: BusinessPipelineService) -> None:
        self.service = service

    def reconcile_all(self, *, limit: int = 200) -> list[BusinessPipelineRunRecord]:
        reconciled: list[BusinessPipelineRunRecord] = []
        for item in self.service.list_runs(limit=limit):
            try:
                reconciled.append(self.service.reconcile(item.pipeline_run_id))
            except Exception:
                logger.exception(
                    "business pipeline reconciliation failed",
                    extra={"pipeline_run_id": item.pipeline_run_id},
                )
        return reconciled
