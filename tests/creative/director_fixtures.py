"""Shared builders for the opt-in Video Bible / Story Director runtime tests.

Everything is synthetic: it exercises typing, routing and persistence. None of it is a
measurement of picture quality.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    OpenAiCompatibleLocalIntelligenceAdapter,
)
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

EVIDENCE = "reviews:key:r1"
V1 = "creative.content_plan.v1"
V2 = "creative.content_plan.v2"
SUBJECT_PHRASE = "Biscuit, a cream golden retriever wearing a teal collar"
PRODUCT_PHRASE = "a small round matte-white tag clipped to the teal collar"
ANCHORS = ["cream golden retriever", "teal collar", "matte-white round tag"]
NOTES = ["Biscuit and the white tag look identical in every shot"]


def seed_result(database: Database) -> str:
    now = datetime.now(UTC).isoformat()
    work_id, result_id = str(uuid4()), str(uuid4())
    result = {
        "schema_version": "1.0",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "summary": "Owners like tags that clip on quickly.",
        "findings": [
            {"rank": 1, "title": "Quick attach", "insight": "Customers mention clip-on speed.",
             "confidence": 0.9, "evidence_ids": [EVIDENCE]}
        ],
        "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }
    database.execute(
        "INSERT INTO business_work_packages(work_package_id,idempotency_key,producer_id,"
        "producer_version,project_key,analysis_profile,objective,status,source_digest,"
        "compressed_size_bytes,manifest_json,created_at,updated_at,finished_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (work_id, f"worker-{work_id}", "test", "1", "pet-tag-us",
         "reviews.voice_of_customer.v1", "x", "Completed", "a" * 64, 1, "{}", now, now, now),
    )
    database.execute(
        "INSERT INTO business_result_packages(result_package_id,work_package_id,analysis_profile,"
        "source_digest,preprocess_digest,model_adapter_version,configured_model_id,"
        "template_version,quality_outcome,result_digest,package_relpath,result_json,"
        "warnings_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (result_id, work_id, "reviews.voice_of_customer.v1", "a" * 64, "b" * 64, "loopback-v1",
         "gpt-oss:20b", "reviews-v1", "PASS", "c" * 64, f"runtime/business/results/{result_id}.zip",
         json.dumps(result), "[]", now),
    )
    return result_id


def stage_outputs(source_ref: str) -> dict[str, dict[str, Any]]:
    ideas = {
        "schema_version": "1.0", "creative_profile": V1,
        "ideas": [
            {"idea_id": f"idea-{i:03d}", "rank": i, "title": f"Idea {i}",
             "audience_problem": "Losing a dog outdoors", "hook": "Clip it on",
             "angle": "ease", "value_proposition": "quick attach", "format_hint": "short video",
             "confidence": 0.8, "source_finding_refs": [source_ref],
             "source_evidence_ids": [EVIDENCE], "claim_risk": "LOW", "warnings": []}
            for i in range(1, 4)
        ],
        "needs_deep_ai": False, "needs_human": False,
    }
    brief = {
        "schema_version": "1.0", "creative_profile": V1, "selected_idea_id": "idea-001",
        "target_audience": "dog owners", "customer_problem": "losing a dog",
        "value_proposition": "quick attach", "primary_hook": "Clip it on",
        "emotional_tone": "warm", "content_format": "short video",
        "duration_min_seconds": 10, "duration_max_seconds": 30,
        "message_hierarchy": ["problem", "solution"],
        "required_source_finding_refs": [source_ref], "required_source_evidence_ids": [EVIDENCE],
        "prohibited_claims": [], "cta_intent": "learn more", "continuity_notes": [],
        "needs_deep_ai": False, "needs_human": False,
    }
    beats = [
        ("beat-001", 4, None, []),
        ("beat-002", 8, "A lightweight tag that clips on in seconds.", [EVIDENCE]),
        ("beat-003", 4, None, []),
    ]
    script = {
        "schema_version": "1.0", "creative_profile": V1, "script_id": "script-001",
        "title": "Clip it on", "target_duration_seconds": 16,
        "beats": [
            {"beat_id": beat_id, "order": order, "duration_seconds": seconds,
             "voiceover": voiceover, "on_screen_text": None, "visual_intent": f"beat {order}",
             "claim_source_evidence_ids": evidence, "unsupported_claim": False}
            for order, (beat_id, seconds, voiceover, evidence) in enumerate(beats, start=1)
        ],
        "cta_beat_id": "beat-003", "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }
    return {"idea": ideas, "brief": brief, "script": script, "bible": good_bible()}


def _shot(index, beat, scene, featured, opening, action, closing, framing, movement, handoff,
          risks=()):
    return {
        "shot_id": f"shot-{index:03d}", "beat_id": beat, "order": index, "scene_id": scene,
        "duration_seconds": 4.0, "featured": featured, "opening_state": opening,
        "visible_action": action, "closing_state": closing, "camera_framing": framing,
        "camera_movement": movement, "handoff_to_next": handoff, "risk_flags": list(risks),
    }


def good_bible() -> dict[str, Any]:
    return {
        "schema_version": "video_bible.v1",
        "subject": {
            "subject_id": "biscuit", "kind": "PET", "species": "dog",
            "breed_or_type": "golden retriever", "coat_or_appearance": "cream coat, floppy ears",
            "distinguishing_marks": ["teal collar"], "identity_phrase": SUBJECT_PHRASE,
        },
        "product": {
            "product_id": "pawtrack-mini", "name": "PawTrack Mini", "category": "pet GPS tag",
            "shape_color_material": "small round matte-white tag",
            "identity_phrase": PRODUCT_PHRASE, "logo_policy": "NO_TEXT_OR_LOGO_IN_FRAME",
            "claims": [{
                "claim_id": "c-clip", "text": "a lightweight tag that clips on in seconds",
                "evidence_ids": [EVIDENCE], "verified": True,
            }],
        },
        "scenes": [
            {"scene_id": "porch", "environment_phrase": "sunny wooden porch with a garden behind",
             "lighting_phrase": "soft morning sunlight", "palette": ["cream", "teal", "green"]},
            {"scene_id": "park", "environment_phrase": "open green park with scattered trees",
             "lighting_phrase": "soft morning sunlight", "palette": ["cream", "teal", "green"]},
        ],
        "camera_rules": {
            "screen_direction": "LEFT_TO_RIGHT",
            "allowed_movements": ["STATIC", "SLOW_PUSH_IN", "TRACK_SIDE"],
        },
        "continuity_anchors": list(ANCHORS),
        "global_continuity_notes": list(NOTES),
        "arc": [
            {"beat_id": "beat-001", "role": "HOOK"},
            {"beat_id": "beat-002", "role": "DEMO"},
            {"beat_id": "beat-003", "role": "CTA"},
        ],
        "shots": [
            _shot(1, "beat-001", "porch", ["SUBJECT"], "Biscuit sits on the porch",
                  "Biscuit tilts his head and wags his tail slowly", "Biscuit sits facing camera",
                  "medium shot", "STATIC", "CUT_ON_ACTION"),
            _shot(2, "beat-002", "porch", ["SUBJECT", "PRODUCT"], "close view of the teal collar",
                  "the white tag rests on the collar as Biscuit turns his head slightly",
                  "the tag sits centered on the collar", "close-up", "SLOW_PUSH_IN",
                  "CUT_ON_ACTION", ["PRODUCT_CLOSEUP"]),
            _shot(3, "beat-002", "park", ["SUBJECT"], "Biscuit stands at the edge of the park",
                  "Biscuit runs across the grass from left to right", "Biscuit slows to a trot",
                  "wide shot", "TRACK_SIDE", "CUT_ON_ACTION", ["FAST_MOTION"]),
            _shot(4, "beat-003", "park", ["SUBJECT", "PRODUCT"], "Biscuit trots toward the camera",
                  "Biscuit sits on the grass and looks into the camera",
                  "Biscuit sits with the white tag visible on the collar", "medium shot",
                  "SLOW_PUSH_IN", "SCENE_CHANGE"),
        ],
        "negative_concepts": ["EXTRA_LIMBS", "MORPHING", "DUPLICATED_OBJECTS", "FLICKER"],
        "unverified_fields": ["reference_image"],
        "needs_deep_ai": False, "needs_human": False,
    }


def mutated_bible(**changes: Any) -> dict[str, Any]:
    bible = deepcopy(good_bible())
    bible.update(changes)
    return bible


class OllamaDouble:
    """A real OpenAI-compatible adapter whose HTTP transport records what Ollama would get."""

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = list(outputs)
        self.requests: list[dict[str, Any]] = []
        client = httpx.Client(
            base_url="http://127.0.0.1:11434/v1/", transport=httpx.MockTransport(self._handle)
        )
        self.adapter = OpenAiCompatibleLocalIntelligenceAdapter(
            LocalIntelligenceConfig(), client=client
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(
            {
                "url": str(request.url), "model": body["model"],
                "system": body["messages"][0]["content"],
                "user": body["messages"][1]["content"],
                "temperature": body["temperature"], "max_tokens": body["max_tokens"],
                "response_format": body["response_format"],
            }
        )
        if not self.outputs:
            raise AssertionError("unexpected Ollama call")
        content = json.dumps(self.outputs.pop(0))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def data(self, index: int) -> dict[str, Any]:
        """The untrusted-data JSON block of one request."""

        return json.loads(self.requests[index]["user"].split("\nDATA:\n", 1)[1])


@dataclass
class Runtime:
    database: Database
    service: CreativeIntelligenceService
    repository: CreativeRepository
    queue: DiagnosticQueueRepository
    source: CreativeSourceNormalizer
    store: CreativeArtifactStore
    result_id: str
    source_ref: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def coordinator(self, adapter: Any) -> CreativeIntelligenceCoordinator:
        return CreativeIntelligenceCoordinator(
            database=self.database, queue=self.queue, repository=self.repository,
            source_normalizer=self.source, store=self.store, adapter=adapter,
            configured_model_id="gpt-oss:20b",
        )

    def create(self, profile: str, key: str):  # type: ignore[no-untyped-def]
        job = self.service.create_job(
            source_result_package_ids=[self.result_id], creative_profile=profile,
            creative_objective="Create a short product education video.", idempotency_key=key,
        )
        task = next(
            item for item in self.queue.list(limit=50)
            if item.resource_tag == f"creative:{job.creative_job_id}"
        )
        return job, task

    def source_ref_for(self, job_id: str) -> str:
        return self.source.load_persisted_source_set(job_id).findings[0].source_finding_ref


def open_runtime(tmp_path: Path) -> Runtime:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    result_id = seed_result(database)
    repository = CreativeRepository(database)
    queue = DiagnosticQueueRepository(database)
    source = CreativeSourceNormalizer(database)
    store = CreativeArtifactStore(paths)
    service = CreativeIntelligenceService(
        repository=repository, source_normalizer=source, store=store, queue=queue
    )
    return Runtime(database, service, repository, queue, source, store, result_id)
