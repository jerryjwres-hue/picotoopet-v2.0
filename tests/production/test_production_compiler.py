from __future__ import annotations

from uuid import uuid4

from picotoopet_core.production.compiler import compile_production_plan


def _creative_manifest(render_intent: str = "GENERATIVE_VIDEO") -> dict[str, object]:
    # ── 2.3.19.1 Creative Package shape ─────────────────────────────────────
    return {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "creative_job_id": str(uuid4()),
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": "shot-001",
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": 3.0,
                        "subject": "compact pet dryer",
                        "environment": "clean home grooming area",
                        "action": "dryer turns while airflow is demonstrated",
                        "framing": "medium product shot",
                        "lighting_style": "soft daylight",
                        "continuity_keys": ["blue body", "same table"],
                        "required_facts": ["portable size"],
                        "source_evidence_ids": ["reviews:key:r1"],
                        "text_reference": None,
                        "production_notes": "renderer-neutral",
                        "render_intent": render_intent,
                    }
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            }
        },
    }


def test_generating_video_compiles_only_to_frozen_t2v_workflow() -> None:
    job_id = str(uuid4())
    manifest = _creative_manifest()
    plan = compile_production_plan(job_id, manifest, "b" * 64)
    task = plan.tasks[0]

    assert plan.production_profile == "production.comfyui.v1"
    assert task.execution_disposition == "Executable"
    assert task.workflow_id == "comfy.wan22.ti2v5b.t2v.v1"
    assert task.positive_prompt == (
        "compact pet dryer; clean home grooming area; dryer turns while airflow is demonstrated; "
        "medium product shot; soft daylight; blue body, same table; portable size"
    )
    assert task.width == 832
    assert task.height == 480
    assert task.fps == 24
    assert task.frame_count == 81


def test_seed_is_deterministic_and_not_producer_supplied() -> None:
    job_id = str(uuid4())
    manifest = _creative_manifest()
    first = compile_production_plan(job_id, manifest, "b" * 64)
    second = compile_production_plan(job_id, manifest, "b" * 64)

    assert first.tasks[0].seed == second.tasks[0].seed
    assert 0 <= first.tasks[0].seed < 2**63


def test_unsupported_render_intent_fails_closed_to_needs_human() -> None:
    plan = compile_production_plan(str(uuid4()), _creative_manifest("TEXT_CARD"), "b" * 64)
    task = plan.tasks[0]

    assert task.execution_disposition == "NeedsHuman"
    assert task.workflow_id is None
