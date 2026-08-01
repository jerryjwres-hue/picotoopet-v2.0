import pytest

from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.queue.state_machine import InvalidTransitionError, ensure_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.CREATED, TaskStatus.VALIDATING),
        (TaskStatus.VALIDATING, TaskStatus.QUEUED),
        (TaskStatus.VALIDATING, TaskStatus.WAITING_FOR_APPROVAL),
        (TaskStatus.QUEUED, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.WAITING_FOR_TOOL),
        (TaskStatus.RUNNING, TaskStatus.RETRYING),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.WAITING_FOR_TOOL, TaskStatus.QUEUED),
        (TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.QUEUED),
        (TaskStatus.RETRYING, TaskStatus.QUEUED),
        (TaskStatus.COMPLETED, TaskStatus.ARCHIVED),
    ],
)
def test_allowed_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    """冻结状态机中允许的转换必须通过。"""

    ensure_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.CREATED, TaskStatus.RUNNING),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.QUEUED),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING),
        (TaskStatus.ARCHIVED, TaskStatus.CREATED),
    ],
)
def test_forbidden_task_transitions_raise(current: TaskStatus, target: TaskStatus) -> None:
    """终态和跳级转换必须被拒绝。"""

    with pytest.raises(InvalidTransitionError):
        ensure_transition(current, target)
