"""SQLite 事务型事件 Outbox。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from uuid import uuid4

from pydantic import BaseModel

from picotoopet_core.db.database import Database


class OutboxEvent(BaseModel):
    """Outbox 投递与重放使用的稳定事件信封。"""

    sequence: int
    outbox_id: str
    topic: str
    payload: dict[str, object]
    trace_id: str | None
    created_at: datetime
    delivery_attempts: int

    def to_envelope(self) -> dict[str, object]:
        """转换为 WebSocket 与客户端共同使用的 V2 信封。"""

        return {
            "schema_version": "2.2.0",
            "sequence": self.sequence,
            "event_id": self.outbox_id,
            "topic": self.topic,
            "trace_id": self.trace_id,
            "created_at": self.created_at.isoformat(),
            "payload": dict(self.payload),
        }


class EventOutbox:
    """保证进程崩溃后事件仍可领取、重放和确认。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, topic: str, payload: dict[str, object], trace_id: str | None = None) -> str:
        """在独立事务中追加一个事件。"""

        with self.database.transaction() as connection:
            return self.append_in_transaction(
                connection,
                topic=topic,
                payload=payload,
                trace_id=trace_id,
            )

    def append_in_transaction(
        self,
        connection: Connection,
        *,
        topic: str,
        payload: dict[str, object],
        trace_id: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        """复用调用方事务追加事件，避免业务状态与通知分裂。"""

        outbox_id = str(uuid4())
        now       = created_at or datetime.now(UTC)
        connection.execute(
            """
            INSERT INTO event_outbox (
                outbox_id, topic, payload_json, trace_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                outbox_id,
                topic,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                trace_id,
                now.isoformat(),
            ),
        )
        return outbox_id

    def list_after(self, sequence: int, *, limit: int = 500) -> list[OutboxEvent]:
        """按 SQLite 行序号读取指定位置之后的持久事件。"""

        bounded = max(1, min(limit, 2000))
        rows    = self.database.fetchall(
            """
            SELECT rowid AS sequence, *
            FROM event_outbox
            WHERE rowid > ?
            ORDER BY rowid ASC
            LIMIT ?
            """,
            (max(0, sequence), bounded),
        )
        return [self._row_to_event(row) for row in rows]

    def claim(
        self,
        worker: str,
        *,
        limit: int,
        stale_after_seconds: int = 60,
    ) -> list[OutboxEvent]:
        """领取未投递或领取状态已过期的事件。"""

        now       = datetime.now(UTC)
        stale_cut = now - timedelta(seconds=stale_after_seconds)
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT rowid AS sequence, *
                FROM event_outbox
                WHERE delivered_at IS NULL
                  AND (claimed_at IS NULL OR claimed_at <= ?)
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (stale_cut.isoformat(), max(1, limit)),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE event_outbox
                    SET claimed_at = ?, claimed_by = ?, delivery_attempts = delivery_attempts + 1
                    WHERE outbox_id = ?
                    """,
                    (now.isoformat(), worker, row["outbox_id"]),
                )
            return [self._row_to_event(row, attempt_increment=1) for row in rows]

    def acknowledge(self, outbox_id: str) -> None:
        """标记事件已经成功送入实时广播层。"""

        now = datetime.now(UTC)
        self.database.execute(
            "UPDATE event_outbox SET delivered_at = ? WHERE outbox_id = ?",
            (now.isoformat(), outbox_id),
        )

    @staticmethod
    def _row_to_event(row, *, attempt_increment: int = 0) -> OutboxEvent:  # type: ignore[no-untyped-def]
        """把 SQLite 行转换为稳定事件模型。"""

        return OutboxEvent(
            sequence=int(row["sequence"]),
            outbox_id=row["outbox_id"],
            topic=row["topic"],
            payload=json.loads(row["payload_json"]),
            trace_id=row["trace_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            delivery_attempts=int(row["delivery_attempts"]) + attempt_increment,
        )
