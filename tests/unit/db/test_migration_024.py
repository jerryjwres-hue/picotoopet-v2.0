"""Schema 24: Goal source snapshots, including upgrade of an existing schema-23 database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from picotoopet_core.autonomous.models import GoalCreate, GoalOrigin, PriorityClass
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.creative.models import CreativeProfile
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.db.database import CURRENT_SCHEMA_VERSION, Database

_SHA = "a" * 64


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _goal_and_job(database: Database) -> tuple[str, str]:
    goal = AutonomousGoalRepository(database).create(
        GoalCreate(
            origin=GoalOrigin.HUMAN,
            intent_type="video.creative",
            priority_class=PriorityClass.P1,
            objective="schema 24 upgrade fixture",
            constraints={"read_only_research": True},
            budget_class="local-first",
            idempotency_key="schema24-goal",
        )
    )
    job = CreativeRepository(database).create_job(
        creative_job_id="00000000-0000-4000-8000-000000000024",
        project_key="goal-schema24",
        creative_profile=CreativeProfile.CONTENT_PLAN_V1,
        creative_objective=None,
        objective_digest=_SHA,
        source_set_digest=_SHA,
        idempotency_key="schema24-creative",
    )
    return goal.goal_id, job.creative_job_id


def _insert_source_set(database: Database, job_id: str, goal_id: str) -> None:
    database.execute(
        "INSERT INTO creative_goal_source_sets("
        "creative_job_id,goal_id,discovery_result_hash,synthesis_result_hash,"
        "source_set_digest,source_set_json,created_at) VALUES (?,?,?,?,?,?,?)",
        (job_id, goal_id, _SHA, _SHA, _SHA, "{}", "2026-01-01T00:00:00+00:00"),
    )


def test_schema_24_is_cumulative_idempotent_and_creates_the_source_lineage_table(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        database.apply_migrations()
        latest = database.scalar("SELECT MAX(version) FROM schema_migrations")
        assert latest == CURRENT_SCHEMA_VERSION
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 24") == 1
        columns = {
            row["name"]: row
            for row in database.fetchall("PRAGMA table_info(creative_goal_source_sets)")
        }
        assert set(columns) == {
            "creative_job_id", "goal_id", "discovery_result_hash", "synthesis_result_hash",
            "source_set_digest", "source_set_json", "created_at",
        }
        assert columns["creative_job_id"]["pk"] == 1
        foreign_keys = {
            (row["from"], row["table"], row["on_delete"])
            for row in database.fetchall("PRAGMA foreign_key_list(creative_goal_source_sets)")
        }
        assert foreign_keys == {
            ("creative_job_id", "creative_jobs", "RESTRICT"),
            ("goal_id", "autonomous_goals", "RESTRICT"),
        }
        indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(creative_goal_source_sets)")
        }
        assert "idx_creative_goal_sources_goal" in indexes
    finally:
        database.close()


def test_schema_24_upgrades_an_existing_schema_23_database_without_losing_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        goal_id, job_id = _goal_and_job(database)
        # Stage a real schema-23 database: historical rows exist, migration 24 is not yet applied.
        database.execute("DROP TABLE creative_goal_source_sets")
        database.execute("DELETE FROM schema_migrations WHERE version = 24")
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 23

        database.apply_migrations()

        latest = database.scalar("SELECT MAX(version) FROM schema_migrations")
        assert latest == CURRENT_SCHEMA_VERSION
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 24") == 1
        assert database.scalar("SELECT COUNT(*) FROM autonomous_goals") == 1
        assert database.scalar("SELECT COUNT(*) FROM creative_jobs") == 1
        assert database.scalar("SELECT COUNT(*) FROM creative_goal_source_sets") == 0
        _insert_source_set(database, job_id, goal_id)
        assert database.scalar("SELECT COUNT(*) FROM creative_goal_source_sets") == 1
    finally:
        database.close()


def test_schema_24_enforces_one_snapshot_per_goal_and_restricts_deleting_sources(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        goal_id, job_id = _goal_and_job(database)
        _insert_source_set(database, job_id, goal_id)

        with pytest.raises(sqlite3.IntegrityError):
            _insert_source_set(database, job_id, goal_id)  # job and goal are both unique here
        with pytest.raises(sqlite3.IntegrityError):
            database.execute("DELETE FROM creative_jobs WHERE creative_job_id = ?", (job_id,))
        with pytest.raises(sqlite3.IntegrityError):
            database.execute("DELETE FROM autonomous_goals WHERE goal_id = ?", (goal_id,))
        with pytest.raises(sqlite3.IntegrityError):
            _insert_source_set(database, "missing-job", goal_id)
    finally:
        database.close()
