"""Deterministic structure, provenance, and safety gates for creative stages."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from picotoopet_core.production.profile import (
    DEFAULT_FPS,
    TIMELINE_TOLERANCE_SECONDS,
    VIDEO_OUTPUT_PROFILES,
    frame_count_for_duration,
)

from .director import MAX_SHOT_SECONDS, GoalDirectives, parse_goal_directives
from .models import (
    CreativeBriefResult,
    CreativeQualityDecision,
    CreativeQualityOutcome,
    CreativeRenderIntent,
    CreativeScriptResult,
    CreativeStageKind,
    IdeaRankingResult,
    ShotPlanResult,
)
from .profiles import CreativeProfileDefinition
from .source import NormalizedCreativeSourceSet
from .video_bible import (
    MIN_SHOT_SECONDS,
    VideoBible,
    VideoBibleDraft,
    correction_for,
    evaluate_video_bible,
    seal_bible,
)

# Intents that become a Wan video, so only they are held to the renderer duration limits.
_VIDEO_INTENTS = frozenset(
    {CreativeRenderIntent.GENERATIVE_VIDEO, CreativeRenderIntent.IMAGE_TO_VIDEO}
)


class CreativeQualityGate:
    _MODELS: dict[CreativeStageKind, type[BaseModel]] = {
        CreativeStageKind.IDEA_RANKING: IdeaRankingResult,
        CreativeStageKind.CREATIVE_BRIEF: CreativeBriefResult,
        CreativeStageKind.SCRIPT: CreativeScriptResult,
        CreativeStageKind.VIDEO_BIBLE: VideoBibleDraft,
        CreativeStageKind.SHOT_PLAN: ShotPlanResult,
    }

    def evaluate(
        self,
        *,
        stage_kind: CreativeStageKind,
        profile: CreativeProfileDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous_stages: dict[str, dict[str, Any]],
        raw_result: dict[str, Any],
        objective: str | None = None,
    ) -> tuple[CreativeQualityDecision, BaseModel | None]:
        directives = parse_goal_directives(objective)
        model = self._MODELS[stage_kind]
        try:
            parsed = model.model_validate(raw_result)
        except ValidationError as error:
            return self._retry("RESULT_SCHEMA_INVALID", self._validation_correction(error)), None

        if self.contains_forbidden_output(parsed.model_dump(mode="json")):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.REJECT,
                reasons=["CREATIVE_OUTPUT_FORBIDDEN_PAYLOAD"],
            ), None
        if bool(getattr(parsed, "needs_human", False)):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                reasons=["MODEL_DECLARED_HUMAN_REVIEW"],
            ), parsed
        if bool(getattr(parsed, "needs_deep_ai", False)):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.NEEDS_DEEP_AI,
                reasons=["MODEL_DECLARED_DEEP_AI"],
            ), parsed

        finding_refs = {item.source_finding_ref for item in source_set.findings}
        evidence_ids = set(source_set.evidence_ids)
        if stage_kind is CreativeStageKind.IDEA_RANKING:
            assert isinstance(parsed, IdeaRankingResult)
            used_findings = {ref for idea in parsed.ideas for ref in idea.source_finding_refs}
            used_evidence = {ref for idea in parsed.ideas for ref in idea.source_evidence_ids}
            if not used_findings <= finding_refs:
                return self._retry(
                    "UNKNOWN_SOURCE_FINDING_REF", "Use only supplied source_finding_ref values."
                ), None
            if not used_evidence <= evidence_ids:
                return self._retry(
                    "UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."
                ), None
        elif stage_kind is CreativeStageKind.CREATIVE_BRIEF:
            assert isinstance(parsed, CreativeBriefResult)
            idea_raw = previous_stages.get(CreativeStageKind.IDEA_RANKING.value)
            if not idea_raw:
                return self._retry(
                    "PRIOR_IDEA_STAGE_MISSING", "Reference the validated idea stage."
                ), None
            idea_ids = {item["idea_id"] for item in idea_raw.get("ideas", [])}
            if parsed.selected_idea_id not in idea_ids:
                return self._retry(
                    "SELECTED_IDEA_UNKNOWN", "Select only the validated rank-1 idea ID."
                ), None
            if not set(parsed.required_source_finding_refs) <= finding_refs:
                return self._retry(
                    "UNKNOWN_SOURCE_FINDING_REF", "Use only supplied source_finding_ref values."
                ), None
            if not set(parsed.required_source_evidence_ids) <= evidence_ids:
                return self._retry(
                    "UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."
                ), None
        elif stage_kind is CreativeStageKind.SCRIPT:
            assert isinstance(parsed, CreativeScriptResult)
            used = {
                evidence for beat in parsed.beats for evidence in beat.claim_source_evidence_ids
            }
            if not used <= evidence_ids:
                return self._retry(
                    "UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."
                ), None
            if any(
                beat.claim_source_evidence_ids == [] and beat.unsupported_claim
                for beat in parsed.beats
            ):
                pass
            if directives.shot_count is not None:
                bound = self._script_shot_count_problem(parsed, directives.shot_count)
                if bound is not None:
                    return self._retry(*bound), None
        elif stage_kind is CreativeStageKind.VIDEO_BIBLE:
            assert isinstance(parsed, VideoBibleDraft)
            return self._evaluate_video_bible(parsed, source_set, previous_stages, directives)
        elif stage_kind is CreativeStageKind.SHOT_PLAN:
            assert isinstance(parsed, ShotPlanResult)
            script_raw = previous_stages.get(CreativeStageKind.SCRIPT.value)
            if not script_raw:
                return self._retry(
                    "PRIOR_SCRIPT_STAGE_MISSING", "Reference the validated script stage."
                ), None
            script_beats = {item["beat_id"] for item in script_raw.get("beats", [])}
            shot_beats = {item.beat_id for item in parsed.shots}
            if not shot_beats <= script_beats:
                return self._retry(
                    "UNKNOWN_SCRIPT_BEAT", "Use only validated script beat IDs."
                ), None
            if script_beats - shot_beats:
                return self._retry(
                    "SCRIPT_BEAT_NOT_COVERED", "Cover every validated script beat."
                ), None
            # Early renderer-feasibility screen for video shots. Same frozen
            # 4n+1 frame rule and profile as the actual Production compiler.
            # Older validated packages keep their immutable persisted plans.
            brief_raw = previous_stages.get(CreativeStageKind.CREATIVE_BRIEF.value)
            fps = DEFAULT_FPS
            if brief_raw is not None:
                try:
                    brief = CreativeBriefResult.model_validate(brief_raw)
                except ValidationError:
                    return self._retry(
                        "PRIOR_BRIEF_INVALID",
                        "Use the previously validated creative brief and output profile.",
                    ), None
                fps = VIDEO_OUTPUT_PROFILES[brief.output_profile_id].fps
            problems = self._shot_plan_problems(
                parsed, script_raw, directives, fps=fps
            )
            if problems:
                return CreativeQualityDecision(
                    outcome=CreativeQualityOutcome.RETRY,
                    reasons=[code for code, _ in problems],
                    correction_instruction=" ".join(text for _, text in problems)[:2000],
                ), None
            bible_raw = previous_stages.get(CreativeStageKind.VIDEO_BIBLE.value)
            if bible_raw is not None:
                try:
                    bible = VideoBible.model_validate(bible_raw)
                except ValidationError:
                    return self._retry(
                        "PRIOR_VIDEO_BIBLE_INVALID", "Use the previously validated video bible."
                    ), None
                if [
                    (item.shot_id, item.beat_id, item.order, item.duration_seconds)
                    for item in bible.shots
                ] != [
                    (item.shot_id, item.beat_id, item.order, item.duration_seconds)
                    for item in parsed.shots
                ]:
                    return self._retry(
                        "SHOT_PLAN_BIBLE_MISMATCH",
                        "Shot ids, beats, order and durations must equal the video bible.",
                    ), None
            used = {evidence for shot in parsed.shots for evidence in shot.source_evidence_ids}
            if not used <= evidence_ids:
                return self._retry(
                    "UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."
                ), None

        return CreativeQualityDecision(outcome=CreativeQualityOutcome.PASS), parsed

    @staticmethod
    def _script_shot_count_problem(
        script: CreativeScriptResult, count: int
    ) -> tuple[str, str] | None:
        """A Goal that asks for exactly N shots bounds the script before any shot exists."""

        ceiling = count * MAX_SHOT_SECONDS
        floor = count * MIN_SHOT_SECONDS
        if len(script.beats) > count:
            return (
                "SCRIPT_BEATS_EXCEED_SHOT_COUNT",
                f"The goal requires exactly {count} shots, so use at most {count} script "
                f"beats (each beat needs at least one shot); you returned {len(script.beats)}.",
            )
        if script.target_duration_seconds > ceiling:
            return (
                "SCRIPT_TOO_LONG_FOR_SHOT_COUNT",
                f"The goal requires exactly {count} shots and one shot can last at most "
                f"{MAX_SHOT_SECONDS:.1f} seconds: set target_duration_seconds to at most "
                f"{ceiling:.1f} seconds and size the beat durations to add up to it.",
            )
        if script.target_duration_seconds < floor:
            return (
                "SCRIPT_TOO_SHORT_FOR_SHOT_COUNT",
                f"The goal requires exactly {count} shots of at least {MIN_SHOT_SECONDS:.1f} "
                f"seconds each: set target_duration_seconds to at least {floor:.1f} seconds.",
            )
        return None

    @staticmethod
    def _shot_plan_problems(
        plan: ShotPlanResult,
        script_raw: dict[str, Any],
        directives: GoalDirectives,
        *,
        fps: int,
    ) -> list[tuple[str, str]]:
        """Every defect Production would otherwise hit later, reported in one repair."""

        problems: list[tuple[str, str]] = []
        count = directives.shot_count
        if directives.text_to_video_only:
            offender = next(
                (
                    shot for shot in plan.shots
                    if shot.render_intent is not CreativeRenderIntent.GENERATIVE_VIDEO
                ),
                None,
            )
            if offender is not None:
                problems.append((
                    "RENDER_INTENT_NOT_TEXT_TO_VIDEO",
                    f"Shot {offender.shot_id} uses render_intent {offender.render_intent.value}, "
                    "but the goal is text-to-video only with no reference image or text card: "
                    "use GENERATIVE_VIDEO for every shot and put any text in the script's "
                    "on_screen_text.",
                ))
        if count is not None and len(plan.shots) != count:
            problems.append((
                "SHOT_COUNT_MISMATCH",
                f"The goal requires exactly {count} shots; return exactly {count} shots "
                f"(you returned {len(plan.shots)}), covering every script beat in order.",
            ))
        for shot in plan.shots:
            if shot.render_intent in _VIDEO_INTENTS:
                try:
                    frame_count_for_duration(shot.duration_seconds, fps)
                except ValueError:
                    if count is not None:
                        text = (
                            f"Shot {shot.shot_id} cannot be rendered at "
                            f"{shot.duration_seconds:g} seconds (maximum "
                            f"{MAX_SHOT_SECONDS:.1f}). Keep exactly {count} shots and give "
                            f"every shot between {MIN_SHOT_SECONDS:.1f} and "
                            f"{MAX_SHOT_SECONDS:.1f} seconds; do not add shots."
                        )
                    else:
                        text = (
                            "The Wan video renderer cannot produce this shot duration "
                            f"for shot {shot.shot_id}. Split the beat into shorter "
                            "ordered shots with the same approved beat and evidence IDs; "
                            "preserve the script's target duration and factual claims."
                        )
                    problems.append(("CREATIVE_SHOT_DURATION_UNRENDERABLE", text))
                    break
        try:
            target = float(script_raw["target_duration_seconds"])
        except (KeyError, TypeError, ValueError):
            target = None
        total = sum(shot.duration_seconds for shot in plan.shots)
        if target is not None and abs(total - target) > TIMELINE_TOLERANCE_SECONDS:
            problems.append((
                "SHOT_TIMELINE_MISMATCH",
                f"Shot durations add up to {total:g} seconds but the script target is "
                f"{target:g}; make them agree (within {TIMELINE_TOLERANCE_SECONDS:g} seconds, "
                "ideally equal) without changing the approved beats.",
            ))
        return problems

    def _evaluate_video_bible(
        self,
        draft: VideoBibleDraft,
        source_set: NormalizedCreativeSourceSet,
        previous_stages: dict[str, dict[str, Any]],
        directives: GoalDirectives | None = None,
    ) -> tuple[CreativeQualityDecision, BaseModel | None]:
        brief_raw = previous_stages.get(CreativeStageKind.CREATIVE_BRIEF.value)
        script_raw = previous_stages.get(CreativeStageKind.SCRIPT.value)
        if not brief_raw or not script_raw:
            return self._retry(
                "PRIOR_STAGE_MISSING", "Reference the validated brief and script stages."
            ), None
        try:
            brief = CreativeBriefResult.model_validate(brief_raw)
            script = CreativeScriptResult.model_validate(script_raw)
        except ValidationError:
            return self._retry(
                "PRIOR_STAGE_INVALID", "Use the previously validated brief and script."
            ), None
        findings = evaluate_video_bible(
            draft,
            brief=brief,
            script=script,
            evidence_ids=set(source_set.evidence_ids),
            required_shot_count=None if directives is None else directives.shot_count,
        )
        if any(item.reject for item in findings):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.REJECT,
                reasons=["CREATIVE_OUTPUT_FORBIDDEN_PAYLOAD"],
            ), None
        if findings:
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.RETRY,
                reasons=[item.code for item in findings][:20],
                correction_instruction=correction_for(findings),
            ), None
        sealed = seal_bible(
            draft,
            project_key=source_set.project_key,
            source_set_digest=source_set.source_set_digest,
            selected_idea_id=brief.selected_idea_id,
        )
        return CreativeQualityDecision(outcome=CreativeQualityOutcome.PASS), sealed

    @staticmethod
    def _retry(code: str, correction: str) -> CreativeQualityDecision:
        return CreativeQualityDecision(
            outcome=CreativeQualityOutcome.RETRY,
            reasons=[code],
            correction_instruction=correction,
        )

    @staticmethod
    def _validation_correction(error: ValidationError) -> str:
        locations = [
            ".".join(str(part) for part in item.get("loc", ()))
            for item in error.errors(include_url=False)[:10]
        ]
        return "Repair only the strict JSON schema fields: " + ", ".join(filter(None, locations))

    @staticmethod
    def contains_forbidden_output(value: object) -> bool:
        """Return whether a value carries forbidden execution/configuration authority."""

        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
        # JSON string escaping doubles Windows path separators. Check a copy with
        # separators decoded rather than the escaped JSON representation, or
        # C:\\Users\\... bypasses the legacy forbidden-path marker.
        path_text = encoded.replace("\\\\", "\\")
        markers = (
            "authorization: bearer",
            "system_prompt",
            "comfyworkflow",
            "comfyui workflow",
            "checkpoint_loader",
            "shell=true",
            "powershell.exe",
            "cmd.exe",
            "http://",
            "https://",
            "/users/",
            "c:\\users\\",
        )
        return any(marker in encoded or marker in path_text for marker in markers)
