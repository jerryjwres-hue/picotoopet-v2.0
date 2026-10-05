"""Core-owned conservative arbitration for bounded external coding agents.

The immediate confidence interval below is a deterministic decision band, not a
statistical confidence interval. Provider history uses a real two-sided Wilson
95% interval and deliberately treats sparse/no history conservatively.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderName = Literal["codex", "claude_code"]
ProviderChoice = Literal["none", "codex", "claude_code"]
ProviderReadiness = Literal["ready", "not_authenticated", "unavailable", "policy_blocked"]
DecisionAction = Literal["local_only", "external_provider", "manual_review"]
ValidationOutcome = Literal["pass", "failed", "uncertain"]

_POLICY_VERSION = "frugal-coding.v1"
_Z_95 = 1.959963984540054
_MAX_EXTERNAL_SESSIONS = 2
_UTILITY_THRESHOLD = 0.15
_HISTORY_SUFFICIENT_TRIALS = 10
_CODING_TASK_CLASSES = frozenset(
    {
        "repository_maintenance",
        "bounded_code_repair",
        "technical_diagnostics",
        "implementation_handoff",
        "coding",
        "code_repair",
    }
)


def _clamp(value: float, lower: float, upper: float) -> float:
    """Clamp one finite numeric decision signal to its frozen range."""

    return max(lower, min(upper, float(value)))


def wilson95(successes: int, trials: int) -> tuple[float, float]:
    """Return the two-sided Wilson 95% interval for a binomial success rate."""

    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("provider history counts are invalid")
    if trials == 0:
        return (0.0, 1.0)

    n = float(trials)
    proportion = successes / n
    z2 = _Z_95 * _Z_95
    denominator = 1.0 + z2 / n
    center = (proportion + z2 / (2.0 * n)) / denominator
    margin = (
        _Z_95
        * math.sqrt((proportion * (1.0 - proportion) / n) + (z2 / (4.0 * n * n)))
        / denominator
    )
    return (_clamp(center - margin, 0.0, 1.0), _clamp(center + margin, 0.0, 1.0))


class ProviderHistorySnapshot(BaseModel):
    """Durable aggregate facts for comparable provider coding sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success_count: int = Field(ge=0)
    sample_size: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> ProviderHistorySnapshot:
        if self.success_count > self.sample_size:
            raise ValueError("provider success_count cannot exceed sample_size")
        return self


class ProviderCandidate(BaseModel):
    """One Core-approved provider candidate; callers cannot append execution flags."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    readiness: ProviderReadiness
    expected_quality_uplift: float = Field(ge=0.0, le=1.0)
    history: ProviderHistorySnapshot
    cost_penalty: float = Field(ge=0.0, le=1.0)
    latency_penalty: float = Field(ge=0.0, le=1.0)
    permission_risk: float = Field(ge=0.0, le=1.0)


class FrugalAssessmentSignals(BaseModel):
    """Bounded local facts used to score whether external coding help is justified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_valid: bool
    validation_passed: bool
    coverage: float = Field(ge=0.0, le=1.0)
    contradiction_rate: float = Field(ge=0.0, le=1.0)
    model_confidence: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    retry_count: int = Field(ge=0, le=100)


class FrugalEscalationInput(BaseModel):
    """Core-owned input envelope for one deterministic escalation decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str = Field(min_length=1, max_length=200)
    task_class: str = Field(min_length=1, max_length=120)
    signals: FrugalAssessmentSignals
    candidates: list[ProviderCandidate] = Field(default_factory=list, max_length=2)
    sessions_used: int = Field(default=0, ge=0, le=_MAX_EXTERNAL_SESSIONS)
    attempted_providers: tuple[ProviderName, ...] = ()
    previous_validation_outcome: ValidationOutcome | None = None

    @model_validator(mode="after")
    def _validate_attempts(self) -> FrugalEscalationInput:
        if len(set(self.attempted_providers)) != len(self.attempted_providers):
            raise ValueError("attempted providers must be unique")
        if len(self.attempted_providers) > self.sessions_used:
            raise ValueError("attempted providers cannot exceed sessions_used")
        return self


class ProviderHistoryEvaluation(BaseModel):
    """Read-only statistical projection used by the arbiter and operator UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    sample_size: int = Field(ge=0)
    success_count: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    wilson95_lower: float = Field(ge=0.0, le=1.0)
    wilson95_upper: float = Field(ge=0.0, le=1.0)
    history_sufficient: bool


class ProviderCandidateScore(BaseModel):
    """One bounded provider utility result; it carries no executable arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    utility: float
    eligible: bool
    reason_codes: tuple[str, ...] = ()


class ProviderEscalationDecision(BaseModel):
    """Immutable decision projection suitable for persistence and audit hashing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["frugal-coding.v1"] = _POLICY_VERSION
    goal_id: str
    task_class: str
    eligibility: bool
    action: DecisionAction
    local_quality_score: float = Field(ge=0.0, le=100.0)
    confidence_center: float = Field(ge=0.0, le=1.0)
    confidence_lower: float = Field(ge=0.0, le=1.0)
    confidence_upper: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...]
    candidate_provider_scores: tuple[ProviderCandidateScore, ...]
    provider_history: tuple[ProviderHistoryEvaluation, ...]
    chosen_provider: ProviderChoice
    external_sessions_remaining: int = Field(ge=0, le=_MAX_EXTERNAL_SESSIONS)
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrugalEscalationArbiter:
    """Choose local-only or one bounded provider using source-controlled policy."""

    def decide(self, request: FrugalEscalationInput) -> ProviderEscalationDecision:
        """Return one replay-stable decision; this method never executes a provider."""

        score, center, lower, upper = self._local_assessment(request.signals)
        history = tuple(self._history(candidate) for candidate in request.candidates)
        candidate_scores = tuple(
            self._candidate_score(candidate, request.sessions_used, request.attempted_providers)
            for candidate in request.candidates
        )

        if request.task_class not in _CODING_TASK_CLASSES:
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=False,
                action="local_only",
                reason_codes=("NOT_ELIGIBLE_FOR_CODING_AGENT",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        if request.previous_validation_outcome == "pass":
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=True,
                action="local_only",
                reason_codes=("PROVIDER_RETURN_VALIDATED",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        if request.sessions_used >= _MAX_EXTERNAL_SESSIONS:
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=True,
                action="manual_review",
                reason_codes=("EXTERNAL_SESSION_CAP_REACHED",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        if request.signals.validation_passed and lower >= 0.80:
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=True,
                action="local_only",
                reason_codes=("LOCAL_CONFIDENCE_SUFFICIENT",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        # ── A second paid/limited session needs an explicit failed/uncertain first return. ──
        if request.sessions_used == 1 and request.previous_validation_outcome not in {
            "failed",
            "uncertain",
        }:
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=True,
                action="manual_review",
                reason_codes=("SECOND_PROVIDER_REQUIRES_FAILED_VALIDATION",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        selectable = [item for item in candidate_scores if item.eligible and item.utility > _UTILITY_THRESHOLD]
        if not selectable:
            return self._decision(
                request=request,
                score=score,
                center=center,
                lower=lower,
                upper=upper,
                eligibility=True,
                action="manual_review",
                reason_codes=("NO_PROVIDER_EXCEEDS_FRUGAL_THRESHOLD",),
                candidate_scores=candidate_scores,
                history=history,
                chosen="none",
            )

        # ── Existing verified Codex wins exact cold-start ties; history may override later. ──
        selectable.sort(key=lambda item: (item.utility, item.provider == "codex"), reverse=True)
        chosen = selectable[0].provider
        return self._decision(
            request=request,
            score=score,
            center=center,
            lower=lower,
            upper=upper,
            eligibility=True,
            action="external_provider",
            reason_codes=("EXTERNAL_PROVIDER_JUSTIFIED",),
            candidate_scores=candidate_scores,
            history=history,
            chosen=chosen,
        )

    @staticmethod
    def _local_assessment(signals: FrugalAssessmentSignals) -> tuple[float, float, float, float]:
        """Compute a deterministic quality score and conservative immediate band."""

        model_component = min(signals.model_confidence, 0.80) / 0.80
        score = (
            (20.0 if signals.contract_valid else 0.0)
            + (30.0 if signals.validation_passed else 0.0)
            + 20.0 * signals.coverage
            + 10.0 * (1.0 - signals.contradiction_rate)
            + 10.0 * model_component
            + 10.0 * (1.0 - signals.risk_score)
            - 5.0 * min(signals.retry_count, 2)
        )
        score = _clamp(score, 0.0, 100.0)
        center = score / 100.0
        width = (
            0.05
            + 0.12 * (1.0 - signals.coverage)
            + 0.10 * signals.contradiction_rate
            + 0.08 * signals.risk_score
            + 0.05 * min(signals.retry_count, 2)
        )
        lower = _clamp(center - width, 0.0, 1.0)
        upper = _clamp(center + min(0.08, width * 0.60), 0.0, 1.0)
        return (round(score, 6), round(center, 6), round(lower, 6), round(upper, 6))

    @staticmethod
    def _history(candidate: ProviderCandidate) -> ProviderHistoryEvaluation:
        lower, upper = wilson95(candidate.history.success_count, candidate.history.sample_size)
        rate = (
            candidate.history.success_count / candidate.history.sample_size
            if candidate.history.sample_size
            else 0.0
        )
        return ProviderHistoryEvaluation(
            provider=candidate.provider,
            sample_size=candidate.history.sample_size,
            success_count=candidate.history.success_count,
            success_rate=round(rate, 6),
            wilson95_lower=round(lower, 6),
            wilson95_upper=round(upper, 6),
            history_sufficient=candidate.history.sample_size >= _HISTORY_SUFFICIENT_TRIALS,
        )

    @staticmethod
    def _candidate_score(
        candidate: ProviderCandidate,
        sessions_used: int,
        attempted: tuple[ProviderName, ...],
    ) -> ProviderCandidateScore:
        reasons: list[str] = []
        if candidate.readiness != "ready":
            reasons.append(f"PROVIDER_{candidate.readiness.upper()}")
        if candidate.provider in attempted:
            reasons.append("PROVIDER_ALREADY_ATTEMPTED")
        eligible = not reasons

        lower, _upper = wilson95(candidate.history.success_count, candidate.history.sample_size)
        history_component = lower if candidate.history.sample_size else 0.35
        utility = (
            0.55 * candidate.expected_quality_uplift
            + 0.30 * history_component
            - 0.07 * candidate.cost_penalty
            - 0.04 * candidate.latency_penalty
            - 0.04 * candidate.permission_risk
            - (0.12 if sessions_used == 1 else 0.0)
        )
        if not eligible:
            utility = -1.0
        return ProviderCandidateScore(
            provider=candidate.provider,
            utility=round(utility, 6),
            eligible=eligible,
            reason_codes=tuple(reasons),
        )

    @staticmethod
    def _decision(
        *,
        request: FrugalEscalationInput,
        score: float,
        center: float,
        lower: float,
        upper: float,
        eligibility: bool,
        action: DecisionAction,
        reason_codes: tuple[str, ...],
        candidate_scores: tuple[ProviderCandidateScore, ...],
        history: tuple[ProviderHistoryEvaluation, ...],
        chosen: ProviderChoice,
    ) -> ProviderEscalationDecision:
        remaining = max(
            0,
            _MAX_EXTERNAL_SESSIONS
            - request.sessions_used
            - (1 if chosen != "none" else 0),
        )
        payload = {
            "policy_version": _POLICY_VERSION,
            "goal_id": request.goal_id,
            "task_class": request.task_class,
            "eligibility": eligibility,
            "action": action,
            "local_quality_score": score,
            "confidence_center": center,
            "confidence_lower": lower,
            "confidence_upper": upper,
            "risk_score": request.signals.risk_score,
            "reason_codes": list(reason_codes),
            "candidate_provider_scores": [item.model_dump(mode="json") for item in candidate_scores],
            "provider_history": [item.model_dump(mode="json") for item in history],
            "chosen_provider": chosen,
            "external_sessions_remaining": remaining,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ProviderEscalationDecision(**payload, decision_digest=digest)
