"""Broker 子进程终态的固定事实转换。"""

from __future__ import annotations

from .models import BrokerSessionRecord, BrokerSessionStatus
from .service import BrokerSessionConflict, BrokerSessionService


def mark_timed_out(
    service: BrokerSessionService,
    session_id: str,
) -> BrokerSessionRecord:
    """把非终态 Session 幂等标记为固定 30 秒超时。"""

    current = service.get_session(session_id)
    if current.status is BrokerSessionStatus.TIMED_OUT:
        return current
    if current.status in service._TERMINAL_STATES:
        raise BrokerSessionConflict("终态 Broker Session 不能改写为 timed_out。")
    return service._transition(
        current,
        BrokerSessionStatus.TIMED_OUT,
        failure_code="BROKER_TIMED_OUT",
        finished=True,
    )


def mark_failed(
    service: BrokerSessionService,
    session_id: str,
) -> BrokerSessionRecord:
    """把非终态 Session 幂等标记为固定 Broker 子进程失败。"""

    current = service.get_session(session_id)
    if current.status is BrokerSessionStatus.FAILED:
        return current
    if current.status in service._TERMINAL_STATES:
        raise BrokerSessionConflict("终态 Broker Session 不能改写为 failed。")
    return service._transition(
        current,
        BrokerSessionStatus.FAILED,
        failure_code="BROKER_CHILD_FAILED",
        finished=True,
    )
