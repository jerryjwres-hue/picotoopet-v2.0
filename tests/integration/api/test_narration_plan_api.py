from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

TOKEN = "0123456789abcdef0123456789abcdef"
SECRET_TEXT = "Narrate this secretly."


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=TOKEN)
    return create_app(settings), {"Authorization": f"Bearer {TOKEN}"}


def _manifest(
    creative_package_id: str, creative_job_id: str, shot_beats: list[str]
) -> dict[str, object]:
    def shot(index: int, beat_id: str) -> dict[str, object]:
        return {
            "shot_id": f"shot-{index}",
            "beat_id": beat_id,
            "order": index,
            "duration_seconds": 1.0,
            "subject": "compact pet dryer",
            "environment": "clean grooming area",
            "action": "product rotates",
            "framing": "medium product shot",
            "lighting_style": "soft daylight",
            "continuity_keys": [],
            "required_facts": [],
            "source_evidence_ids": [],
            "text_reference": None,
            "production_notes": "renderer-neutral",
            "render_intent": "GENERATIVE_VIDEO",
        }

    return {
        "schema_version": "1.0",
        "creative_package_id": creative_package_id,
        "creative_job_id": creative_job_id,
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "selected_idea_id": "idea-001",
                "target_audience": "pet owners",
                "customer_problem": "slow drying",
                "value_proposition": "save time",
                "primary_hook": "Dry faster",
                "emotional_tone": "practical",
                "content_format": "short video",
                "duration_min_seconds": 3,
                "duration_max_seconds": 10,
                "message_hierarchy": ["problem", "solution"],
                "required_source_finding_refs": ["result:finding:1"],
                "required_source_evidence_ids": ["reviews:key:r1"],
                "prohibited_claims": [],
                "cta_intent": "learn more",
                "continuity_notes": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Dry faster",
                "target_duration_seconds": float(len(shot_beats)),
                "beats": [
                    {
                        "beat_id": beat_id,
                        "order": order,
                        "duration_seconds": len(shot_beats) / 2,
                        "voiceover": SECRET_TEXT if order == 1 else "Second.",
                        "on_screen_text": None,
                        "visual_intent": "Compact dryer in use",
                        "claim_source_evidence_ids": [],
                        "unsupported_claim": False,
                    }
                    for order, beat_id in enumerate(["beat-1", "beat-2"], start=1)
                ],
                "cta_beat_id": "beat-1",
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [shot(i, beat) for i, beat in enumerate(shot_beats, start=1)],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
        },
    }


def _seed(database, shot_beats: list[str]) -> str:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).isoformat()
    creative_job_id, creative_package_id = str(uuid4()), str(uuid4())
    manifest = _manifest(creative_package_id, creative_job_id, shot_beats)
    database.execute(
        "INSERT INTO creative_jobs("
        "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
        "source_set_digest,status,creative_package_id,idempotency_key,"
        "created_at,updated_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            creative_job_id,
            "pet-dryer-us",
            "creative.content_plan.v1",
            None,
            creative_job_id.replace("-", "") * 2,
            "a" * 64,
            "creative_ready",
            creative_package_id,
            f"creative-{creative_job_id}",
            now,
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO creative_packages("
        "creative_package_id,creative_job_id,source_set_digest,package_digest,"
        "package_relpath,manifest_json,quality_outcome,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            creative_package_id,
            creative_job_id,
            "a" * 64,
            creative_package_id.replace("-", "") * 2,
            f"runtime/creative/packages/{creative_package_id}.zip",
            json.dumps(manifest),
            "PASS",
            now,
        ),
    )
    return creative_package_id


def _create_job(client: TestClient, headers: dict[str, str], package_id: str) -> str:
    response = client.post(
        "/api/v1/production/jobs",
        headers=headers,
        json={
            "creative_package_id": package_id,
            "production_profile": "production.comfyui.v1",
            "idempotency_key": f"narration-{package_id}",
        },
    )
    assert response.status_code == 200
    return response.json()["production_job_id"]


def _url(job_id: str) -> str:
    return f"/api/v1/postproduction/production/{job_id}/narration-plan"


def test_narration_plan_requires_auth(tmp_path: Path) -> None:
    app, _headers = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get(_url(str(uuid4()))).status_code == 401


def test_narration_plan_exact_job_lookup_and_stable_digest(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        database = app.state.services.database
        job_a = _create_job(client, headers, _seed(database, ["beat-1", "beat-1", "beat-2"]))
        job_b = _create_job(client, headers, _seed(database, ["beat-1", "beat-2"]))

        first = client.get(_url(job_a), headers=headers)
        assert first.status_code == 200
        body = first.json()
        assert body["plan"]["production_job_id"] == job_a
        assert [(s["beat_id"], s["start_ms"], s["end_ms"]) for s in body["plan"]["segments"]] == [
            ("beat-1", 0, 2000),
            ("beat-2", 2000, 3000),
        ]
        assert (
            body["plan"]["production_plan_digest"]
            == app.state.services.production.get_job(job_a).plan_digest
        )
        assert client.get(_url(job_a), headers=headers).json() == body

        other = client.get(_url(job_b), headers=headers).json()
        assert other["plan"]["production_job_id"] == job_b
        assert other["narration_plan_digest"] != body["narration_plan_digest"]

        text = json.dumps(body)
        for forbidden in (
            "api_key",
            "token",
            "provider",
            "model_path",
            "executable",
            "C:\\",
            "/Users/",
            ".safetensors",
        ):
            assert forbidden not in text


def test_unknown_job_is_bounded_404(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get(_url(str(uuid4())), headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PRODUCTION_RESOURCE_NOT_FOUND"


def test_job_without_bound_plan_is_not_ready(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        package_id = _seed(services.database, ["beat-1", "beat-2"])
        job_id = str(uuid4())
        services.production_repository.create_job(
            production_job_id=job_id,
            creative_package_id=package_id,
            creative_package_digest="c" * 64,
            project_key="pet-dryer-us",
            production_profile="production.comfyui.v1",
            idempotency_key="not-ready-job",
        )
        response = client.get(_url(job_id), headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NARRATION_PLAN_NOT_READY"


def test_invalid_timeline_is_bounded_typed_error_without_text(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        job_id = _create_job(
            client, headers, _seed(app.state.services.database, ["beat-1", "beat-2", "beat-1"])
        )
        response = client.get(_url(job_id), headers=headers)
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "NARRATION_TIMELINE_AMBIGUOUS"
        assert SECRET_TEXT not in response.text
