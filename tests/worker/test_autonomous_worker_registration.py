"""The Worker must register local intelligence only through one explicit fixed task type."""

from __future__ import annotations

from picotoopet_core.worker.handlers import HandlerResult, default_handlers


def _fake_local_handler(task) -> HandlerResult:  # type: ignore[no-untyped-def]
    return HandlerResult(summary={"task_type": task.task_type})


def test_default_handlers_do_not_claim_local_intelligence_without_injected_handler() -> None:
    handlers = default_handlers()
    assert "autonomous.local_analysis.v1" not in handlers


def test_injected_local_handler_is_registered_under_one_fixed_task_type() -> None:
    handlers = default_handlers(local_intelligence_handler=_fake_local_handler)
    assert handlers["autonomous.local_analysis.v1"] is _fake_local_handler
    assert not any(key.startswith("autonomous.") for key in handlers if key != "autonomous.local_analysis.v1")
