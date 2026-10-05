"""Durable Mac Core repository for immutable frugal escalation decisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database

from .frugal import ProviderEscalationDecision


class FrugalDecisionRecord(BaseModel):
    """Read-only persisted projection around one immutable arbiter decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    goal_id: str
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    chosen_provider: str
    decision: ProviderEscalationDecision
    created_at: datetime


class FrugalDecisionRepository:
    """Append-only decision store; clients never provide authoritative provider policy."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def put(self, decision: ProviderEscalationDecision) -> FrugalDecisionRecord:
        """Persist one verified decision, replaying the same digest idempotently."""

        self._verify_digest(decision)
        existing = self._by_digest(decision.decision_digest)
        if existing is not None:
            if existing.decision != decision:
                raise ValueError("FRUGAL_DECISION_DIGEST_COLLISION")
            return existing

        decision_id = str(uuid4())
        created_at = datetime.now(UTC)
        decision_json = json.dumps(
            decision.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO deep_ai_frugal_decisions (
                        decision_id, goal_id, decision_digest, policy_version,
                        chosen_provider, decision_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        decision.goal_id,
                        decision.decision_digest,
                        decision.policy_version,
                        decision.chosen_provider,
                        decision_json,
                        created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError:
            # ── Concurrent replay of the same digest is still one immutable fact. ──
            replay = self._by_digest(decision.decision_digest)
            if replay is None or replay.decision != decision:
                raise
            return replay
        return self.get(decision_id)

    def get(self, decision_id: str) -> FrugalDecisionRecord:
        """Read one durable decision by Core-generated identity."""

        row = self.database.fetchone(
            "SELECT * FROM deep_ai_frugal_decisions WHERE decision_id = ?",
            (decision_id,),
        )
        if row is None:
            raise KeyError(decision_id)
        return self._record(row)

    def latest_for_goal(self, goal_id: str) -> FrugalDecisionRecord:
        """Return the latest immutable decision for one Goal."""

        row = self.database.fetchone(
            """
            SELECT * FROM deep_ai_frugal_decisions
            WHERE goal_id = ?
            ORDER BY created_at DESC, decision_id DESC
            LIMIT 1
            """,
            (goal_id,),
        )
        if row is None:
            raise KeyError(goal_id)
        return self._record(row)

    def list_for_goal(self, goal_id: str, *, limit: int = 100) -> list[FrugalDecisionRecord]:
        """Return bounded decision history, newest first."""

        safe_limit = max(1, min(int(limit), 500))
        rows = self.database.fetchall(
            """
            SELECT * FROM deep_ai_frugal_decisions
            WHERE goal_id = ?
            ORDER BY created_at DESC, decision_id DESC
            LIMIT ?
            """,
            (goal_id, safe_limit),
        )
        return [self._record(row) for row in rows]

    def _by_digest(self, digest: str) -> FrugalDecisionRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM deep_ai_frugal_decisions WHERE decision_digest = ?",
            (digest,),
        )
        return None if row is None else self._record(row)

    @staticmethod
    def _verify_digest(decision: ProviderEscalationDecision) -> None:
        payload = decision.model_dump(mode="json", exclude={"decision_digest"})
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if expected != decision.decision_digest:
            raise ValueError("FRUGAL_DECISION_DIGEST_MISMATCH")

    @staticmethod
    def _record(row) -> FrugalDecisionRecord:  # type: ignore[no-untyped-def]
        decision = ProviderEscalationDecision.model_validate(json.loads(row["decision_json"]))
        return FrugalDecisionRecord(
            decision_id=row["decision_id"],
            goal_id=row["goal_id"],
            decision_digest=row["decision_digest"],
            policy_version=row["policy_version"],
            chosen_provider=row["chosen_provider"],
            decision=decision,
            created_at=row["created_at"],
        )
