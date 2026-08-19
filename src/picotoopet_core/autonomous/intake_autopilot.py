"""Convert trusted connected-evidence events into existing Goal Center workflows.

Connected programs still submit evidence only. Mac Core owns the product-visible
Goal, priority, constraints and fixed workflow plan; no caller can select a task
type, provider, prompt, shell command or account write operation through intake.
"""

from __future__ import annotations

import hashlib

from picotoopet_core.automation.service import WorkflowService

from .connected_evidence import ConnectedEvidenceRepository
from .human_pipeline import HumanGoalWorkflowPlanner
from .models import GoalCreate, GoalOrigin, GoalRecord, PriorityClass
from .repository import AutonomousGoalRepository

_MAX_CONNECTED_PRODUCT_KEYS = 8
_MAX_PRODUCT_KEY_CHARS = 200
_AUTO_OBJECTIVE = (
    "自动分析本次新接入的公开证据，筛选有价值的消费者痛点、商业机会和可用于 "
    "AI 视频制作的内容方向，并生成可追溯的 Web GPT 交接包。"
)


class ConnectedIntakeAutopilot:
    """Create one replay-safe P2 Goal for one successful canonical intake event."""

    def __init__(
        self,
        *,
        evidence: ConnectedEvidenceRepository,
        goals: AutonomousGoalRepository,
        workflows: WorkflowService,
        planner: HumanGoalWorkflowPlanner | None = None,
    ) -> None:
        self.evidence = evidence
        self.goals = goals
        self.workflows = workflows
        self.planner = planner or HumanGoalWorkflowPlanner()

    def trigger(
        self,
        *,
        source: str,
        event_id: str,
        product_keys: list[str] | tuple[str, ...],
    ) -> GoalRecord:
        """Materialize the existing research-to-video pipeline without executing providers inline."""

        safe_source = source.strip()
        safe_event_id = event_id.strip()
        if not safe_source or len(safe_source) > 80:
            raise ValueError("connected intake source is invalid")
        if not safe_event_id or len(safe_event_id) > 200:
            raise ValueError("connected intake event_id is invalid")

        normalized = self._validated_product_keys(product_keys)
        key_material = f"{safe_source}\n{safe_event_id}".encode("utf-8")
        event_hash = hashlib.sha256(key_material).hexdigest()[:32]
        goal = self.goals.create(
            GoalCreate(
                origin=GoalOrigin.AUTONOMOUS,
                intent_type="product.research_to_video",
                priority_class=PriorityClass.P2,
                objective=_AUTO_OBJECTIVE,
                constraints={
                    "auto_trigger_source": safe_source,
                    "connected_product_keys": list(normalized),
                    "depth": "standard",
                    "external_ai_upload_requires_user_action": True,
                    "product_visible": True,
                    "read_only_research": True,
                },
                budget_class="local-first",
                idempotency_key=f"connected-intake:{event_hash}",
            )
        )
        if goal.workflow_id is None:
            workflow = self.workflows.create_workflow(self.planner.plan(goal))
            goal = self.goals.bind_workflow(goal.goal_id, workflow.workflow_id)

        # ── Reconcile only schedules registered capabilities; it never executes a provider inline. ──
        assert goal.workflow_id is not None
        self.workflows.reconcile(goal.workflow_id)
        return self.goals.get(goal.goal_id)

    def _validated_product_keys(
        self,
        product_keys: list[str] | tuple[str, ...],
    ) -> tuple[str, ...]:
        values: list[str] = []
        for raw in product_keys:
            value = str(raw).strip()
            if not value or len(value) > _MAX_PRODUCT_KEY_CHARS:
                raise ValueError("connected product key is invalid")
            if value in values:
                continue
            # ── Only Mac Core canonical product keys can become an automatic analysis scope. ──
            self.evidence.get_product(value)
            values.append(value)
        if not values or len(values) > _MAX_CONNECTED_PRODUCT_KEYS:
            raise ValueError("connected product scope must contain 1-8 canonical products")
        return tuple(values)
