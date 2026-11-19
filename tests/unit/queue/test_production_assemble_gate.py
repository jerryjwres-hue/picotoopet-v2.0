"""QC production gate: a picked clip is not an approved clip."""

from types import SimpleNamespace

import pytest

from picotoopet_core.queue.production import ProductionService


def candidate(*, decision="pick", qc=None):
    # 只模拟这里读取的候选字段，避免生成测试素材或启动 GPU。
    return SimpleNamespace(kind="video", decision=decision, qc=qc or {})


def approved_qc():
    # 此数据来自具备产物哈希对应关系的当前轮次 QC 报告。
    return {
        "gate_status": "Completed",
        "report_task_id": "qc-current",
        "passed": True,
        "superseded": False,
    }


def test_current_certified_pick_can_assemble():
    picked = candidate(qc=approved_qc())
    assert ProductionService._certified_video([picked]) is picked


@pytest.mark.parametrize(
    "change",
    [
        {"gate_status": "QC_REGENERATING"},
        {"gate_status": "QC_MANUAL_REVIEW"},
        {"gate_status": "Queued"},
        {"report_task_id": None},
        {"passed": False},
        {"passed": None},
        {"superseded": True},
        {"superseded": None},
    ],
)
def test_uncertified_or_outdated_pick_cannot_assemble(change):
    qc = {**approved_qc(), **change}
    assert ProductionService._certified_video([candidate(qc=qc)]) is None


def test_unreviewed_import_and_duplicate_picks_cannot_assemble():
    # 仅被人工选用、但没有当前 QC 证明的历史视频必须阻断。
    assert ProductionService._certified_video([candidate(qc={"score": 95})]) is None
    current = candidate(qc=approved_qc())
    assert ProductionService._certified_video([current, candidate(qc=approved_qc())]) is None
    assert ProductionService._certified_video([current, candidate(decision=None)]) is current
