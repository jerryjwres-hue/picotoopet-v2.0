"""#177 real FastAPI Core/SQLite interop on disposable Windows CI only.

No production classes are patched, no user database is opened, no operator
enrollment is simulated over HTTP, and no renderer/GPU code is executed.
The fixture public key is inserted directly into a runner-only temporary DB.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import production
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.db.database import Database
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService
from picotoopet_core.production.store import ProductionArtifactStore
from picotoopet_core.production.versioned_plan import (
    ProductionJobCreateV11Request, ProductionPlanV11,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
EXECUTOR = "windows-same-exe-worker"
TEST_ONLY = "P0_REAL_CORE_LOCALHOST_CI_ONLY"
MANIFEST = "interop-fixture-public.json"


def guard(root: Path) -> None:
    # ── A fake operator identity is only a unit fixture on an ephemeral runner.
    if os.environ.get("CI") != "true" or os.environ.get(TEST_ONLY) != "1":
        raise SystemExit("REAL_CORE_INTEROP_REQUIRES_EPHEMERAL_CI")
    if os.name != "nt" or not root.is_absolute():
        raise SystemExit("REAL_CORE_INTEROP_REQUIRES_WINDOWS_TEMP_ROOT")
    if "p0-real-core-interop-" not in root.name or not root.exists():
        raise SystemExit("REAL_CORE_INTEROP_TEMP_ROOT_INVALID")


def db_at(root: Path) -> Database:
    db = Database(RuntimePaths.from_root(root / "core").database_file)
    db.open()
    db.apply_migrations()
    return db


def seed(root: Path, identity_file: Path) -> None:
    # ── Reuse actual Core reference consent and ProductionPlanV11 compiler
    # ── from the already existing Python production test fixtures.
    tests = Path(__file__).resolve().parents[1] / "production"
    sys.path.insert(0, str(tests))
    import test_reference_registration_api as fixture
    sha = hashlib.sha256(PNG).hexdigest()
    fixture.SHA = sha
    original = fixture.candidate

    def candidate(shot: str) -> dict:
        value = original(shot)
        value["bytes"] = len(PNG)
        return value

    fixture.candidate = candidate
    state_fixture = fixture.state.__wrapped__(root / "core")
    state = next(state_fixture)
    try:
        db, _, _, _, _ = state
        batch = fixture._approve_batch(state)
        service = fixture._v11_service(state)
        job = service.create_job_v11(ProductionJobCreateV11Request(
            creative_package_id=fixture.PACKAGE,
            idempotency_key="real-windows-http-core-only-ci",
            approved_reference_ids=[batch.approval_id],
        ))
        full = service.get_plan(job.production_job_id)
        # ── One frozen I2V shot for existing Windows preflight client's
        # ── all-reference contract; do not alter compiler or production path.
        single = ProductionPlanV11.model_validate({
            **full.model_dump(mode="json"),
            "target_runtime_ms": full.tasks[0].target_duration_ms,
            "tasks": [full.tasks[0].model_dump(mode="json")],
        })
        raw = single.model_dump(mode="json")
        digest = service._digest(raw)
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM production_tasks WHERE production_job_id=? "
                "AND production_task_id<>?",
                (job.production_job_id, single.tasks[0].production_task_id),
            )
            connection.execute(
                "UPDATE production_jobs SET plan_digest=?,plan_json=? "
                "WHERE production_job_id=?",
                (
                    digest, json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    job.production_job_id,
                ),
            )
        assert service.repository.plan_for(job.production_job_id) == single
        identity = json.loads(identity_file.read_text(encoding="utf-8"))
        pub = bytes.fromhex(identity["public_key_hex"])
        assert len(pub) == 32
        fingerprint = hashlib.sha256(pub).hexdigest()
        key_id = "wk-" + fingerprint[:40]
        assert identity["key_id"] == key_id
        assert identity["fingerprint"] == fingerprint
        # ── White-box insertion ONLY into a disposable DB, NOT a bearer route
        # ── or an assertion that a user completed genuine Mac console pairing.
        db.execute(
            "INSERT INTO production_worker_keys("
            "key_id,executor_id,public_key_hex,key_fingerprint,registered_by,"
            "operator_receipt_sha256,enrolled_at) VALUES (?,?,?,?,?,?,?)",
            (
                key_id, EXECUTOR, pub.hex(), fingerprint,
                "CI_FIXTURE_NOT_OPERATOR", "a" * 64, datetime.now(UTC).isoformat(),
            ),
        )
        (root / MANIFEST).write_text(
            json.dumps({
                "job_id": job.production_job_id,
                "plan_digest": digest,
                "approval_id": batch.approval_id,
                "key_id": key_id,
                "executor_id": EXECUTOR,
                "image_sha256": sha,
                "image_bytes": len(PNG),
                "image_relative_path": single.tasks[0].reference_asset.input_relative_path,
            }, sort_keys=True) + "\n", encoding="utf-8",
        )
        print("REAL_CORE_SEED=PASS; FROZEN_PLAN=PASS; TEST_ONLY_KEY=PASS")
    finally:
        try:
            next(state_fixture)
        except StopIteration:
            pass


def serve(root: Path, port: int) -> None:
    # ── Real production FastAPI router, authentication and error handlers;
    # ── only the service wiring is ephemeral, not a fake route/dispatcher.
    import uvicorn
    db = db_at(root)
    service = ProductionService(
        repository=ProductionRepository(db),
        creative_repository=CreativeRepository(db),
        store=ProductionArtifactStore(RuntimePaths.from_root(root / "core")),
    )
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(
        production=service,
        settings=SimpleNamespace(api_token=os.environ["P0_CORE_INTEROP_BEARER"]),
    )
    print("REAL_CORE_FASTAPI_LISTEN=127.0.0.1", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def mutate(root: Path, action: str) -> None:
    db = db_at(root)
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        if action == "revoke":
            db.execute(
                "UPDATE approvals SET status='Rejected' WHERE approval_id=?",
                (manifest["approval_id"],),
            )
        elif action == "expire":
            db.execute(
                "UPDATE production_worker_challenges SET issued_at=?,expires_at=? "
                "WHERE production_job_id=?",
                (
                    (datetime.now(UTC) - timedelta(seconds=70)).isoformat(),
                    (datetime.now(UTC) - timedelta(seconds=40)).isoformat(),
                    manifest["job_id"],
                ),
            )
        elif action == "assert":
            rows = db.fetchall(
                "SELECT * FROM production_worker_challenges WHERE production_job_id=?",
                (manifest["job_id"],),
            )
            expected = int(os.environ.get("P0_CORE_INTEROP_EXPECT_CHALLENGES", "1"))
            assert len(rows) == expected, "exact REAL Core-issued challenge count expected"
            assert len({row["nonce_digest"] for row in rows}) == expected
            for row in rows:
                assert row["consumed_at"] is None, "preflight cannot consume nonce"
                assert row["key_id"] == manifest["key_id"]
                assert row["plan_digest"] == manifest["plan_digest"]
                assert row["executor_id"] == EXECUTOR
            assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0
            assert db.scalar(
                "SELECT COUNT(*) FROM production_tasks WHERE attempt_count<>0 "
                "OR comfy_prompt_id IS NOT NULL OR status='Running'"
            ) == 0
            job = db.fetchone(
                "SELECT * FROM production_jobs WHERE production_job_id=?",
                (manifest["job_id"],),
            )
            assert job["lease_token_digest"] is None
            assert job["lease_executor_id"] is None
            assert job["lease_expires_at"] is None
            assert job["plan_digest"] == manifest["plan_digest"]
            assert db.scalar("SELECT COUNT(*) FROM production_packages") == 0
            print("REAL_CORE_SQLITE_NONCE=UNSPENT; LEASE=0; ATTEMPT=0; RESULT=0; GPU=BLOCKED")
        else:
            raise ValueError("unknown test-only action")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "serve", "assert", "revoke", "expire"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--port", type=int)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    guard(root)
    if arguments.action == "seed":
        if arguments.identity is None:
            raise SystemExit("missing disposable Windows public key")
        seed(root, arguments.identity)
    elif arguments.action == "serve":
        if arguments.port is None or not (1024 <= arguments.port <= 65535):
            raise SystemExit("invalid loopback port")
        serve(root, arguments.port)
    else:
        mutate(root, arguments.action)
