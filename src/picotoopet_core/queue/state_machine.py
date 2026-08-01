"""冻结任务状态机。"""

from __future__ import annotations

from picotoopet_core.domain.enums import TaskStatus


class InvalidTransitionError(ValueError):
    """任务状态转换不符合冻结契约。"""


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.VALIDATING, TaskStatus.CANCELLED}),
    TaskStatus.VALIDATING: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_FOR_TOOL,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.RETRYING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_FOR_TOOL: frozenset(
        {TaskStatus.QUEUED, TaskStatus.RETRYING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING_FOR_APPROVAL: frozenset(
        {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RETRYING: frozenset(
        {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset({TaskStatus.ARCHIVED}),
    TaskStatus.FAILED: frozenset({TaskStatus.ARCHIVED}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.ARCHIVED}),
    TaskStatus.ARCHIVED: frozenset(),
}


def ensure_transition(current: TaskStatus, target: TaskStatus) -> None:
    """验证状态转换；不合法时抛出明确异常。"""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"不允许从 {current.value} 转换到 {target.value}。")
