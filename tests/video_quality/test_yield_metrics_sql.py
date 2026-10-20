"""The documented yield queries must run on the real schema and mean what the doc says.

The rows below are SYNTHETIC fixtures that exercise the arithmetic. They are not measurements
and say nothing about real render time, yield or quality.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database

SQL = (
    Path(__file__).resolve().parents[2] / "docs" / "p0_video_quality" / "yield_metrics.sql"
).read_text(encoding="utf-8")
JOB = "job-yield-fixture"


def _statements() -> list[str]:
    body = "\n".join(line for line in SQL.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip() for part in body.split(";") if part.strip()]


def _run(database: Database, statement: str, job: str) -> list:
    # Named parameters need the raw connection (Database.execute only accepts positional ones).
    return database.connection.execute(statement, {"job": job}).fetchall()


def _one(rows: list):
    assert len(rows) == 1
    return rows[0]


def _at(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"2026-01-01T00:{minutes:02d}:{rest:02d}+00:00"


@pytest.fixture
def database(tmp_path: Path):
    db = Database(tmp_path / "core.db")
    db.open()
    db.apply_migrations()
    db.execute(
        "INSERT INTO production_jobs(production_job_id,creative_package_id,creative_package_digest,"
        "project_key,production_profile,status,idempotency_key,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (JOB, "cp", "a" * 64, "goal-x", "production.comfyui.v1", "Rendering", "idem-yield",
         _at(0), _at(0)),
    )
    tasks = [
        # (task, order, status, attempt_count, finished_at)
        ("t1", 1, "Succeeded", 1, _at(70)),
        ("t2", 2, "Succeeded", 2, _at(161)),
        ("t3", 3, "Running", 1, None),
    ]
    for task_id, order, status, attempts, finished in tasks:
        db.execute(
            "INSERT INTO production_tasks(production_task_id,production_job_id,shot_id,order_index,"
            "render_intent,execution_disposition,workflow_id,task_plan_json,status,attempt_count,"
            "created_at,updated_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, JOB, f"shot-{order}", order, "GENERATIVE_VIDEO", "Executable", "w", "{}",
             status, attempts, _at(0), _at(0), finished),
        )
    attempts = [
        # (task, n, status, start, finish, failure_code)
        ("t1", 1, "Succeeded", _at(10), _at(70), None),
        ("t2", 1, "Failed", _at(80), _at(100), "COMFY_RETRYABLE_LOCAL_FAILURE"),
        ("t2", 2, "Succeeded", _at(101), _at(161), None),
        ("t3", 1, "Running", _at(170), None, None),
    ]
    for task_id, number, status, start, finish, code in attempts:
        db.execute(
            "INSERT INTO production_attempts(production_attempt_id,production_job_id,"
            "production_task_id,attempt_number,executor_id,status,started_at,finished_at,"
            "failure_code) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{task_id}-{number}", JOB, task_id, number, "exec", status, start, finish, code),
        )
    yield db
    db.close()


def test_documented_queries_are_two_read_only_selects() -> None:
    statements = _statements()
    assert len(statements) == 2
    for statement in statements:
        assert re.match(r"(?is)^select\b", statement)
        assert not re.search(r"(?i)\b(insert|update|delete|drop|alter|create)\b", statement)


def test_job_metrics_match_the_fixture_arithmetic(database: Database) -> None:
    row = _one(_run(database, _statements()[0], JOB))
    assert row["tasks_total"] == 3
    assert row["tasks_succeeded"] == 2
    assert row["tasks_first_pass"] == 1  # only t1 succeeded on its first attempt
    assert row["attempts_on_succeeded_tasks"] == 3  # 1 + 2
    assert row["tasks_not_executable"] == 0
    assert row["attempt_wall_seconds_finished"] == 140.0  # 60 + 20 + 60
    assert row["attempts_unfinished"] == 1
    assert row["seconds_to_first_shot"] == 70.0
    assert row["seconds_to_package"] is None  # no package yet: never invented

    database.execute(
        "INSERT INTO production_packages(production_package_id,production_job_id,"
        "creative_package_id,plan_digest,package_digest,package_relpath,manifest_json,"
        "quality_outcome,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("pkg", JOB, "cp", "b" * 64, "c" * 64, "p", "{}", "PASS", _at(300)),
    )
    assert _one(_run(database, _statements()[0], JOB))["seconds_to_package"] == 300.0


def test_not_executable_tasks_are_counted(database: Database) -> None:
    database.execute(
        "UPDATE production_tasks SET execution_disposition='NeedsHuman', workflow_id=NULL "
        "WHERE production_task_id='t3'"
    )
    assert _one(_run(database, _statements()[0], JOB))["tasks_not_executable"] == 1


def test_failure_distribution_counts_only_recorded_codes(database: Database) -> None:
    rows = _run(database, _statements()[1], JOB)
    assert [(r["failure_code"], r["attempts"]) for r in rows] == [
        ("COMFY_RETRYABLE_LOCAL_FAILURE", 1)
    ]


def test_unknown_job_yields_no_invented_numbers(database: Database) -> None:
    assert _run(database, _statements()[0], "missing") == []
    assert _run(database, _statements()[1], "missing") == []
