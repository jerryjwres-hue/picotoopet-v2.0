"""Bounded human Goal Center contracts over the canonical autonomous Goal repository."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import GoalCreate, GoalOrigin, GoalRecord, PriorityClass
from .repository import AutonomousGoalRepository


class HumanGoalType(StrEnum):
    """Product-facing goals Windows may request without exposing task types."""

    PRODUCT_RESEARCH = "product.research"
    CONSUMER_PAIN_POINTS = "consumer.pain_points"
    BUSINESS_OPPORTUNITY = "business.opportunity"
    VIDEO_CREATIVE = "video.creative"
    PRODUCT_RESEARCH_TO_VIDEO = "product.research_to_video"


class GoalDepth(StrEnum):
    """Stable research depth profiles; Core still owns concrete stop conditions."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class HumanGoalRequest(BaseModel):
    """Small public request surface; callers cannot choose priority, origin or task type."""

    model_config = ConfigDict(extra="forbid")

    goal_type: HumanGoalType
    objective: str = Field(min_length=1, max_length=4000)
    depth: GoalDepth = GoalDepth.STANDARD


class GoalTemplate(BaseModel):
    """One visible Goal Center suggestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_type: HumanGoalType
    title: str
    description: str
    example: str


_TEMPLATES = (
    GoalTemplate(
        goal_type=HumanGoalType.PRODUCT_RESEARCH,
        title="研究一个产品",
        description="自动补齐公开资料、消费者证据并形成可追溯结论。",
        example="研究这款大型犬耐咬玩具，告诉我值不值得做。",
    ),
    GoalTemplate(
        goal_type=HumanGoalType.CONSUMER_PAIN_POINTS,
        title="找消费者痛点",
        description="聚合真实证据，提炼抱怨、购买阻力和未满足需求。",
        example="找出大型犬玩具最常见的消费者痛点和购买阻力。",
    ),
    GoalTemplate(
        goal_type=HumanGoalType.BUSINESS_OPPORTUNITY,
        title="寻找商业机会",
        description="基于证据判断需求缺口、受众和可验证机会。",
        example="从现有研究里找最值得验证的三个产品机会。",
    ),
    GoalTemplate(
        goal_type=HumanGoalType.VIDEO_CREATIVE,
        title="生成 AI 视频方案",
        description="把已有可信结论转换为视频创意 Brief 和网页 GPT 交接包。",
        example="用已有证据做一个适合 TikTok 的 30 秒 AI 视频方案。",
    ),
    GoalTemplate(
        goal_type=HumanGoalType.PRODUCT_RESEARCH_TO_VIDEO,
        title="从产品研究到视频",
        description="自动完成研究、补证、分析、创意和 Web GPT 交接包。",
        example="研究这个产品，然后直接给我可用于 AI 视频制作的完整方案。",
    ),
)


class HumanGoalService:
    """Translate product-facing goals into durable, replay-safe Mac Core Goal facts."""

    def __init__(self, repository: AutonomousGoalRepository) -> None:
        self.repository = repository

    @staticmethod
    def templates() -> list[GoalTemplate]:
        return list(_TEMPLATES)

    def create(self, request: HumanGoalRequest, *, idempotency_key: str) -> GoalRecord:
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        return self.repository.create(
            GoalCreate(
                origin=GoalOrigin.HUMAN,
                intent_type=request.goal_type.value,
                priority_class=PriorityClass.P1,
                objective=request.objective.strip(),
                constraints={
                    "depth": request.depth.value,
                    "external_ai_upload_requires_user_action": True,
                    "read_only_research": True,
                },
                budget_class="local-first",
                idempotency_key=f"human:{key}",
            )
        )

    def list(self, *, limit: int = 200) -> list[GoalRecord]:
        return [
            goal
            for goal in self.repository.list(limit=limit)
            if goal.origin is GoalOrigin.HUMAN
        ]

    def get(self, goal_id: str) -> GoalRecord:
        goal = self.repository.get(goal_id)
        if goal.origin is not GoalOrigin.HUMAN:
            raise KeyError(f"human goal not found: {goal_id}")
        return goal
