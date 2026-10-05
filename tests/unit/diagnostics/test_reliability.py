"""Superpower v1 reliability faults must be deterministic and composable."""

from __future__ import annotations

from datetime import UTC, datetime

from picotoopet_core.diagnostics.reliability import (
    ReliabilityFaultCode,
    ReliabilityObservation,
    classify_reliability,
)


def _observation(**overrides: object) -> ReliabilityObservation:
    payload: dict[str, object] = {
        "observed_at": datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        "core_reachable": True,
        "event_stream_connected": True,
        "worker_status_stale": False,
        "active_task_lease_alive": False,
        "ollama_server_reachable": True,
        "model_job_timed_out": False,
        "model_output_invalid": False,
        "memory_pressure": "normal",
        "active_task_id": None,
        "active_stage": None,
        "input_chars": None,
    }
    payload.update(overrides)
    return ReliabilityObservation.model_validate(payload)


def test_worker_status_stale_while_lease_alive_is_a_distinct_fault() -> None:
    snapshot = classify_reliability(
        _observation(
            worker_status_stale=True,
            active_task_lease_alive=True,
            active_task_id="task-long-model",
            active_stage="local-analysis",
        )
    )

    expected = ReliabilityFaultCode.WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE
    assert snapshot.primary_fault is expected
    assert snapshot.status == "failed"
    assert snapshot.active_task_id == "task-long-model"
    assert snapshot.active_stage == "local-analysis"


def test_event_stream_transient_does_not_mark_reachable_core_offline() -> None:
    snapshot = classify_reliability(_observation(event_stream_connected=False))

    assert snapshot.primary_fault is ReliabilityFaultCode.EVENT_STREAM_TRANSIENT
    assert snapshot.status == "degraded"
    assert snapshot.core_reachable is True


def test_core_unreachable_outranks_event_stream_disconnect() -> None:
    snapshot = classify_reliability(
        _observation(
            core_reachable=False,
            event_stream_connected=False,
        )
    )

    assert snapshot.primary_fault is ReliabilityFaultCode.CORE_UNREACHABLE
    assert ReliabilityFaultCode.EVENT_STREAM_TRANSIENT not in snapshot.faults
    assert snapshot.status == "failed"


def test_ollama_model_and_memory_failures_are_classified_without_guessing() -> None:
    cases = [
        (
            {"ollama_server_reachable": False},
            ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE,
            "failed",
        ),
        (
            {"model_job_timed_out": True},
            ReliabilityFaultCode.MODEL_JOB_TIMEOUT,
            "failed",
        ),
        (
            {"model_output_invalid": True},
            ReliabilityFaultCode.MODEL_OUTPUT_INVALID,
            "failed",
        ),
        (
            {"memory_pressure": "high"},
            ReliabilityFaultCode.MEMORY_PRESSURE_HIGH,
            "degraded",
        ),
    ]

    for overrides, expected_fault, expected_status in cases:
        snapshot = classify_reliability(_observation(**overrides))
        assert snapshot.primary_fault is expected_fault
        assert snapshot.status == expected_status


def test_multiple_faults_preserve_stable_priority_and_all_known_faults() -> None:
    snapshot = classify_reliability(
        _observation(
            event_stream_connected=False,
            ollama_server_reachable=False,
            model_job_timed_out=True,
            memory_pressure="high",
            input_chars=23000,
        )
    )

    assert snapshot.primary_fault is ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE
    assert snapshot.faults == (
        ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE,
        ReliabilityFaultCode.MODEL_JOB_TIMEOUT,
        ReliabilityFaultCode.MEMORY_PRESSURE_HIGH,
        ReliabilityFaultCode.EVENT_STREAM_TRANSIENT,
    )
    assert snapshot.input_chars == 23000


def test_healthy_observation_has_no_fault_code() -> None:
    snapshot = classify_reliability(_observation())

    assert snapshot.status == "healthy"
    assert snapshot.primary_fault is None
    assert snapshot.faults == ()
