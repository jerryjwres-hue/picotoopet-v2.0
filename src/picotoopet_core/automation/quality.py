"""Persisted quality-gate decisions for workflow steps."""

from __future__ import annotations

from .models import QualityDecision, QualityDecisionRecord
from .repository import AutomationRepository


class QualityGate:
    """Record a bounded workflow decision; never performs paid inference itself."""

    def __init__(self, repository: AutomationRepository) -> None:
        self.repository = repository

    def decide(self, decision: QualityDecision) -> QualityDecisionRecord:
        record = self.repository.record_quality_decision(decision)
        self.repository.apply_quality_outcome(decision)
        self.repository.record_checkpoint(
            decision.workflow_id,
            step_key=decision.step_key,
            state={
                "event": "quality.decision",
                "step_key": decision.step_key,
                "outcome": decision.outcome.value,
                "rule_id": decision.rule_id,
            },
        )
        return record
