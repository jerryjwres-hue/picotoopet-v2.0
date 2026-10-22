"""Every way a Creative stage can end, and what each costs (model attempts, handoff, status).

Real Coordinator + SQLite + the production Ollama adapter over a recording transport. Scripted
synthetic outputs; this pins recovery behaviour, not picture quality.
"""

from __future__ import annotations

import pytest
from director_fixtures import V1, V2, OllamaDouble, Runtime, good_bible, open_runtime, stage_outputs
from test_three_shot_reliability import GOAL, _script, _shots

from picotoopet_core.business.local_intelligence import LocalIntelligenceError
from picotoopet_core.creative.repository import CreativeRepository


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def _job(rt: Runtime, profile: str = V1, key: str = "recovery"):  # type: ignore[no-untyped-def]
    job = rt.service.create_job(
        source_result_package_ids=[rt.result_id], creative_profile=profile,
        creative_objective=GOAL, idempotency_key=key,
    )
    task = next(i for i in rt.queue.list(limit=50)
                if i.resource_tag == f"creative:{job.creative_job_id}")
    return job, task


def _front(rt: Runtime, job_id: str) -> list[dict]:
    parts = stage_outputs(rt.source_ref_for(job_id))
    return [parts["idea"], parts["brief"], _script(3, 4.0)]


def _plan(shots: list[dict]) -> dict:
    return {"schema_version": "1.0", "creative_profile": V1, "shots": shots, "warnings": [],
            "needs_deep_ai": False, "needs_human": False}


def _stage(rt: Runtime, job_id: str, kind: str) -> dict:
    row = rt.database.fetchone(
        "SELECT * FROM creative_stage_runs WHERE creative_job_id=? AND stage_kind=?",
        (job_id, kind),
    )
    return dict(row)


def _bad_plan() -> dict:
    shots = _shots(3)["shots"]
    for shot in shots:
        shot["continuity_keys"] = []
    return _plan(shots)


def test_first_pass(runtime: Runtime) -> None:
    job, task = _job(runtime)
    double = OllamaDouble([*_front(runtime, job.creative_job_id), _plan(_shots(3)["shots"])])
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "creative_ready"
    stage = _stage(runtime, job.creative_job_id, "shot_plan.v1")
    assert (stage["status"], stage["model_attempts"], len(double.requests)) == ("Completed", 1, 4)


def test_one_repair_then_pass_costs_exactly_one_extra_call(runtime: Runtime) -> None:
    job, task = _job(runtime)
    double = OllamaDouble(
        [*_front(runtime, job.creative_job_id), _bad_plan(), _plan(_shots(3)["shots"])]
    )
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "creative_ready"
    stage = _stage(runtime, job.creative_job_id, "shot_plan.v1")
    assert (stage["status"], stage["model_attempts"], len(double.requests)) == ("Completed", 2, 5)
    assert "continuity_keys of EVERY shot" in double.requests[4]["user"]
    assert runtime.service.get_handoff(job.creative_job_id) is None


def test_two_failed_attempts_end_in_needs_deep_ai_with_a_manual_handoff(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime)
    double = OllamaDouble([*_front(runtime, job.creative_job_id), _bad_plan(), _bad_plan()])
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "NeedsDeepAI"
    stage = _stage(runtime, job.creative_job_id, "shot_plan.v1")
    assert (stage["status"], stage["model_attempts"], len(double.requests)) == (
        "NEEDS_DEEP_AI", 2, 5
    )
    handoff = runtime.service.get_handoff(job.creative_job_id)
    assert handoff is not None and handoff.status == "ManualReady"
    assert "SHOT_IDENTITY_ANCHORS_MISSING" in handoff.quality_reasons
    # A restart neither calls the model again nor changes the outcome.
    again = runtime.coordinator(OllamaDouble([]).adapter).handler(task)
    assert again.summary["status"] == "NeedsDeepAI"


def test_local_model_failure_is_needs_human_after_one_attempt(runtime: Runtime) -> None:
    job, task = _job(runtime)

    class Failing:
        calls = 0

        def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
            Failing.calls += 1
            raise LocalIntelligenceError("LOCAL_MODEL_TIMEOUT")

    summary = runtime.coordinator(Failing()).handler(task)
    assert summary.summary["status"] == "NeedsHuman"
    assert Failing.calls == 1  # no second attempt is spent on an unavailable model
    assert runtime.repository.get_job(job.creative_job_id).failure_code == "LOCAL_MODEL_TIMEOUT"


def test_model_declared_human_review_is_needs_human(runtime: Runtime) -> None:
    job, task = _job(runtime)
    idea = _front(runtime, job.creative_job_id)[0]
    idea["needs_human"] = True
    summary = runtime.coordinator(OllamaDouble([idea]).adapter).handler(task)
    assert summary.summary["status"] == "NeedsHuman"


def test_forbidden_payload_is_rejected_without_retry(runtime: Runtime) -> None:
    job, task = _job(runtime)
    shots = _shots(3)["shots"]
    shots[0]["environment"] = "see https://example.invalid/dog"
    double = OllamaDouble([*_front(runtime, job.creative_job_id), _plan(shots)])
    assert runtime.coordinator(double.adapter).handler(task).summary["status"] == "Rejected"
    assert len(double.requests) == 4


def test_v2_bible_exhaustion_is_needs_human_and_never_a_hosted_handoff(
    runtime: Runtime,
) -> None:
    job, task = _job(runtime, V2, "recovery-v2")
    broken = good_bible()
    broken["arc"].pop()
    double = OllamaDouble([*_front(runtime, job.creative_job_id), broken, broken])
    runtime.coordinator(double.adapter).handler(task)
    record = runtime.repository.get_job(job.creative_job_id)
    assert record.failure_code == "CREATIVE_VIDEO_BIBLE_UNRESOLVED"
    assert runtime.service.get_handoff(job.creative_job_id) is None


# ── restart between the two attempts ───────────────────────────────────────────────────


def test_restart_between_attempts_still_carries_the_repair_instruction(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    job, task = _job(runtime)
    first = OllamaDouble([*_front(runtime, job.creative_job_id), _bad_plan()])
    original = CreativeRepository.update_stage

    def crash_on_second_attempt(self, stage_run_id, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("status") == "Running" and kwargs.get("model_attempts") == 2:
            raise RuntimeError("worker killed between attempts")
        return original(self, stage_run_id, **kwargs)

    monkeypatch.setattr(CreativeRepository, "update_stage", crash_on_second_attempt)
    with pytest.raises(RuntimeError, match="worker killed"):
        runtime.coordinator(first.adapter).handler(task)
    monkeypatch.setattr(CreativeRepository, "update_stage", original)

    stage = _stage(runtime, job.creative_job_id, "shot_plan.v1")
    assert (stage["status"], stage["model_attempts"]) == ("Retry", 1)

    second = OllamaDouble([_plan(_shots(3)["shots"])])
    summary = runtime.coordinator(second.adapter).handler(task)
    assert summary.summary["status"] == "creative_ready"
    retry = second.requests[0]["user"]
    assert "Correction for this one retry only:" in retry
    assert "continuity_keys of EVERY shot" in retry
    assert _stage(runtime, job.creative_job_id, "shot_plan.v1")["model_attempts"] == 2


def test_a_crash_inside_the_second_model_call_spends_the_stage_budget(
    runtime: Runtime,
) -> None:
    """Known, deliberate cost: attempts are counted before the call, so a worker killed
    mid-call leaves no attempt for the restart and the stage goes to the Deep-AI handoff."""

    job, task = _job(runtime)
    outputs = [*_front(runtime, job.creative_job_id), _bad_plan()]

    class CrashOnSecond:
        def __init__(self) -> None:
            self.double = OllamaDouble(outputs)

        def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
            if len(self.double.requests) == 4:
                self.double.requests.append({})
                raise RuntimeError("killed mid-call")
            return self.double.adapter.run(profile, context, correction=correction)

    with pytest.raises(RuntimeError, match="killed mid-call"):
        runtime.coordinator(CrashOnSecond()).handler(task)
    summary = runtime.coordinator(OllamaDouble([]).adapter).handler(task)
    assert summary.summary["status"] == "NeedsDeepAI"
