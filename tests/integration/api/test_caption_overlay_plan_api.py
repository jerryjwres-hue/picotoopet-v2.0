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
SECRET_OVERLAY = "SECRET-OVERLAY-CONTENT"
PACKAGE_DIGEST = "b" * 64


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=TOKEN)
    return create_app(settings), {"Authorization": f"Bearer {TOKEN}"}


def _manifest(
    creative_package_id: str,
    creative_job_id: str,
    shot_beats: list[str],
    *,
    overlay_by_beat: dict[str, str | None] | None = None,
    render_intents: list[str] | None = None,
) -> dict[str, object]:
    # ── Fixtures keep Creative timing valid while C005 task ms remains authoritative. ──
    overlay_by_beat = overlay_by_beat or {}
    render_intents = render_intents or ["GENERATIVE_VIDEO"] * len(shot_beats)
    unique_beats = list(dict.fromkeys(shot_beats))
    target_seconds = float(len(shot_beats))

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
            "render_intent": render_intents[index - 1],
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
                "target_duration_seconds": target_seconds,
                "beats": [
                    {
                        "beat_id": beat_id,
                        "order": order,
                        "duration_seconds": target_seconds / len(unique_beats),
                        "voiceover": f"Narration for {beat_id}.",
                        "on_screen_text": overlay_by_beat.get(beat_id),
                        "visual_intent": "Compact dryer in use",
                        "claim_source_evidence_ids": [],
                        "unsupported_claim": False,
                    }
                    for order, beat_id in enumerate(unique_beats, start=1)
                ],
                "cta_beat_id": unique_beats[0],
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


def _seed(
    database,  # type: ignore[no-untyped-def]
    shot_beats: list[str],
    *,
    overlay_by_beat: dict[str, str | None] | None = None,
    render_intents: list[str] | None = None,
) -> str:
    now = datetime.now(UTC).isoformat()
    creative_job_id, creative_package_id = str(uuid4()), str(uuid4())
    manifest = _manifest(
        creative_package_id,
        creative_job_id,
        shot_beats,
        overlay_by_beat=overlay_by_beat,
        render_intents=render_intents,
    )
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
            PACKAGE_DIGEST,
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
            "idempotency_key": f"caption-overlay-{package_id}",
        },
    )
    assert response.status_code == 200
    return response.json()["production_job_id"]


def _url(job_id: str) -> str:
    return f"/api/v1/postproduction/production/{job_id}/caption-overlay-plan"


def _counts(database) -> dict[str, int]:  # type: ignore[no-untyped-def]
    # ── GET must not create lifecycle rows or schema objects. ─────────────────
    tables = ("creative_jobs", "creative_packages", "production_jobs", "production_tasks")
    counts = {
        table: int(database.fetchone(f"SELECT COUNT(*) AS count FROM {table}")["count"])
        for table in tables
    }
    counts["schema_tables"] = int(
        database.fetchone("SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table'")["count"]
    )
    return counts


def test_caption_overlay_plan_requires_auth_and_exact_path(tmp_path: Path) -> None:
    app, _headers = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get(_url(str(uuid4())))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_valid_plan_returns_stable_digest_and_exact_overlay_window(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed(
            app.state.services.database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Dry faster"},
        )
        job_id = _create_job(client, headers, package_id)
        first = client.get(_url(job_id), headers=headers)
        second = client.get(_url(job_id), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    body = first.json()
    assert body["plan"]["production_job_id"] == job_id
    assert body["plan"]["captions"] == []
    assert body["plan"]["captions_required"] is False
    assert body["plan"]["overlays_required"] is True
    assert [
        (cue["beat_id"], cue["start_ms"], cue["end_ms"])
        for cue in body["plan"]["overlays"]
    ] == [("beat-1", 0, 2000)]
    assert len(body["caption_overlay_plan_digest"]) == 64


def test_unknown_job_is_bounded_404(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get(_url(str(uuid4())), headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCTION_RESOURCE_NOT_FOUND"
    assert response.json()["error"]["retryable"] is False


def test_job_without_bound_plan_is_retryable_not_ready(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        package_id = _seed(
            services.database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = str(uuid4())
        services.production_repository.create_job(
            production_job_id=job_id,
            creative_package_id=package_id,
            creative_package_digest=PACKAGE_DIGEST,
            project_key="pet-dryer-us",
            production_profile="production.comfyui.v1",
            idempotency_key="caption-overlay-not-ready",
        )
        response = client.get(_url(job_id), headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TEXT_PRESENTATION_NOT_READY"
    assert response.json()["error"]["retryable"] is True


def test_source_mismatch_is_bounded_422(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        database = app.state.services.database
        package_id = _seed(
            database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = _create_job(client, headers, package_id)
        database.execute(
            "UPDATE production_jobs SET creative_package_digest=? WHERE production_job_id=?",
            ("e" * 64, job_id),
        )
        response = client.get(_url(job_id), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_PRESENTATION_SOURCE_MISMATCH"
    assert response.json()["error"]["retryable"] is False


def test_timeline_ambiguity_is_bounded_422(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed(
            app.state.services.database,
            ["beat-1", "beat-2", "beat-1"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = _create_job(client, headers, package_id)
        response = client.get(_url(job_id), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_text_card_with_authored_overlay_is_bounded_ambiguity_without_text_leak(
    tmp_path: Path,
) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed(
            app.state.services.database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": SECRET_OVERLAY},
            render_intents=["TEXT_CARD", "GENERATIVE_VIDEO", "GENERATIVE_VIDEO"],
        )
        job_id = _create_job(client, headers, package_id)
        response = client.get(_url(job_id), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS"
    assert SECRET_OVERLAY not in response.text


def test_response_contains_no_credentials_paths_or_raw_renderer_authority(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed(
            app.state.services.database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = _create_job(client, headers, package_id)
        response = client.get(_url(job_id), headers=headers)

    assert response.status_code == 200
    forbidden_keys = {
        "provider",
        "model",
        "path",
        "font_path",
        "filter",
        "command",
        "url",
        "executable",
        "width",
        "height",
        "fps",
        "api_key",
        "token",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    assert keys(response.json()).isdisjoint(forbidden_keys)
    text = response.text
    assert "C:\\" not in text
    assert "/Users/" not in text


def test_get_projection_does_not_mutate_rows_or_schema(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        database = app.state.services.database
        package_id = _seed(
            database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = _create_job(client, headers, package_id)
        before = _counts(database)
        response = client.get(_url(job_id), headers=headers)
        after = _counts(database)

    assert response.status_code == 200
    assert after == before


def test_c007a_narration_endpoint_remains_green(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed(
            app.state.services.database,
            ["beat-1", "beat-1", "beat-2"],
            overlay_by_beat={"beat-1": "Visible"},
        )
        job_id = _create_job(client, headers, package_id)
        response = client.get(
            f"/api/v1/postproduction/production/{job_id}/narration-plan",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["plan"]["production_job_id"] == job_id
