"""Combined real HTTP preflight always blocks production until independent gates exist."""

from __future__ import annotations

import base64
import copy
import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.security.owner_principal import (
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

_ROOT = "/api/v1/studio/storypacks/owner-review"
_SUBJECT = "pet:maotai"
_SYNTHETIC_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZcAAAAASUVORK5CYII="
)


def _pack() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "MAOTAI_READINESS",
        "title": "Maotai dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "style_ref": "toon_style_v1",
        "story": {"goal": "Find dinner", "payoff": "Look to the door"},
        "shots": [
            {
                "id": "S01", "action": "Fetch the ball",
                "state_in": "Dog on grass", "state_out": "Dog holding ball",
                "because": "Build anticipation",
            },
            {
                "id": "S02", "action": "Turn to doorway",
                "state_in": "Dog holding ball", "state_out": "Dog looking at door",
                "because": "Owner calls", "depends_on": ["S01"],
                "handoff": "continuous",
            },
        ],
    }


def _complete() -> dict:
    return {
        "edit": {"loudness_lufs": -14.0},
        "shots": [
            {
                "shot_id": ident,
                "emotion": "curious",
                "camera": {"move": "locked-off", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": [f"unapproved-first-frame-{index}.png"],
                    "prompt": "Synthetic image, not owner-approved",
                },
                "video": {
                    "prompt": f"One motion for {ident}",
                    "negative": "flicker",
                    "seeds": [100 + index],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for index, ident in enumerate(("S01", "S02"))
        ],
    }


@pytest.fixture
def context(tmp_path):
    owner = secrets.token_urlsafe(32)
    device = secrets.token_urlsafe(32)
    master = secrets.token_urlsafe(32)
    registry = OwnerReviewRegistry(credentials=(
        OwnerCredentialConfig(
            credential_id="readiness-owner",
            actor_id="owner-operator",
            token_sha256=owner_token_fingerprint(owner),
            subject_keys=(_SUBJECT,),
            permissions=("storypack.review", "asset_use.attest", "production.admit"),
            registry_revision=1, enabled=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        OwnerCredentialConfig(
            credential_id="readiness-master",
            actor_id="independent-master-reviewer",
            token_sha256=owner_token_fingerprint(master),
            subject_keys=(_SUBJECT,), permissions=("master.verify",),
            registry_revision=1, enabled=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ))
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path), api_token=device,
        owner_review_registry=registry,
        # 仅合成测试启用第二组 Worker HMAC 凭据；实际默认关闭。
        worker_attestation_id="win-worker-test",
        worker_attestation_key="w" * 48,
        scoped_gpu_admission_enabled=True,  # CPU-only synth lease: no Comfy/GPU.
    ))
    with TestClient(app, client=("127.0.0.1", 59100)) as client:
        # 测试使用独立 Reviewer 凭据，不赋予原 Owner MASTER 权限。
        client.app.state.synthetic_master_token = master
        svc = app.state.services
        objects = {}
        svc.database.execute(
            """INSERT INTO projects
               (project_id,title,project_type,source_app,classification,status,
                created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
            ("ready-test", "Synthetic", "pet", "test", "internal",
             "Active", "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"),
        )
        for index, ref in enumerate(("maotai_master_v1", "backyard_v1", "toon_style_v1")):
            # 完全合成的有效 PNG 魔数，三个身份仍然拥有不同字节及 SHA。
            stored = svc.results.put_bytes(
                _SYNTHETIC_PNG + bytes([index]), result_type="image"
            )
            objects[ref] = stored.object_hash
            svc.database.execute(
                """INSERT INTO artifacts (
                   artifact_id,project_id,artifact_type,classification,
                   sha256,stored_object_hash,is_original,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (ref, "ready-test", "image", "internal", stored.object_hash,
                 stored.object_hash, 1, "2026-11-19T00:00:00Z"),
            )
        yield client, owner, device, objects


def _call(client, suffix, data, token, *, key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(_ROOT + suffix, json=data, headers=headers)


def _create_reviewed_candidate(client, owner, objects):
    pack = _pack()
    base = {"subject_key": _SUBJECT, "storypack": pack}
    preview = _call(client, "/preview", base, owner)
    assert preview.status_code == 200, preview.text
    subject = preview.json()
    commit = _call(client, "/commit", {
        **base,
        "expected_subject_sha256": subject["review"]["subject_sha256"],
        "expires_seconds": 900,
    }, owner, key="readiness-storyboard-001")
    assert commit.status_code == 200, commit.text

    claims = [
        {
            "ref": ref, "asset_sha256": digest, "basis": "self_created",
            "commercial_ai_generation": True, "commercial_distribution": True,
        }
        for ref, digest in sorted(objects.items())
    ]
    proof = _call(client, "/asset-use/preview", {**base, "claims": claims}, owner)
    assert proof.status_code == 200, proof.text
    attestation = _call(client, "/asset-use/commit", {
        **base, "claims": claims,
        "expected_attestation_sha256": proof.json()["attestation_sha256"],
        "expires_seconds": 900,
    }, owner, key="readiness-asset-use-001")
    assert attestation.status_code == 200, attestation.text
    return {
        **base,
        "claims": claims,
        "storyboard_review_id": commit.json()["review_id"],
        "attestation_id": attestation.json()["attestation_id"],
        "storypack_sha256": subject["storypack_sha256"],
        "completion": _complete(),
    }


def _assert_no_production(client):
    db = client.app.state.services.database
    for table in ("tasks", "production_episodes", "approvals"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0, table


def test_valid_owner_proofs_and_complete_episode_still_cannot_create_jobs(context):
    client, owner, device, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    before = client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    )
    response = _call(client, "/production-readiness", payload, owner)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "BLOCKED_PRODUCTION_ADMISSION"
    assert report["checks"]["storyboard_review_current"] is True
    assert report["checks"]["asset_use_attestation_current"] is True
    assert report["checks"]["episode_contract_valid"] is True
    assert report["checks"]["episode_budget_allowed"] is True
    assert report["candidate_episode_sha256"]
    assert report["budget_preview"]["initial_video_takes"] == 2
    assert report["checks"]["master_rights_independently_verified"] is False
    assert "MASTER_RIGHTS_NOT_VERIFIED" in report["blocking_reasons"]
    assert "GPU_HOLD_NOT_RELEASED" in report["blocking_reasons"]
    assert report["can_queue"] is False
    assert report["can_generate"] is False
    assert report["read_only"] is True
    assert _call(client, "/production-readiness", payload, device).status_code == 403
    assert _call(client, "/production-readiness", payload, owner).json() == report
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    ) == before
    _assert_no_production(client)


def test_revoke_or_mutate_evidence_surfaces_blockers_without_new_tasks(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    revoked = _call(client, "/revoke", {
        "subject_key": _SUBJECT,
        "review_id": payload["storyboard_review_id"],
    }, owner)
    assert revoked.status_code == 200, revoked.text
    invalid = _call(client, "/production-readiness", payload, owner)
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["checks"]["storyboard_review_current"] is False
    assert "OWNER_STORYBOARD_REVIEW_REVOKED" in invalid.json()["blocking_reasons"]

    # Replacing bytes invalidates the separate asset-use assertion as well.
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered")
    stale = _call(client, "/production-readiness", payload, owner)
    assert stale.status_code == 200, stale.text
    assert stale.json()["checks"]["asset_use_attestation_current"] is False
    assert stale.json()["checks"]["storyboard_review_current"] is False
    _assert_no_production(client)


def test_invalid_episode_or_budget_is_displayed_but_never_queued(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    bad = copy.deepcopy(payload)
    bad["completion"]["shots"][1]["shot_id"] = "S99"
    response = _call(client, "/production-readiness", bad, owner)
    assert response.status_code == 200, response.text
    assert response.json()["checks"]["episode_contract_valid"] is False
    assert "EPISODE_SHOT_ORDER_OR_ID_DRIFT" in response.json()["blocking_reasons"]

    budget = copy.deepcopy(payload)
    budget["completion"]["shots"][0]["video"]["seeds"] = list(range(9))
    result = _call(client, "/production-readiness", budget, owner)
    assert result.status_code == 200, result.text
    assert result.json()["checks"]["episode_contract_valid"] is True
    assert result.json()["checks"]["episode_budget_allowed"] is False
    assert "EPISODE_BUDGET_EXCEEDED" in result.json()["blocking_reasons"]
    _assert_no_production(client)



def test_managed_frame_ids_bind_sha_but_windows_worker_remains_unverified(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)

    # 使用当前 StoryPack 的角色与场景 ID，而非凭空猜测的 Windows 路径。
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "backyard_v1",
    ]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = [
        "maotai_master_v1",
    ]
    result = _call(client, "/production-readiness", payload, owner)
    assert result.status_code == 200, result.text
    report = result.json()
    refs = report["frame_reference_preview"]

    assert report["checks"]["first_frame_mac_content_bound"] is True
    assert report["checks"]["first_frame_worker_local_verified"] is False
    assert refs["status"] == "MAC_CONTENT_BOUND_WORKER_STAGING_REQUIRED"
    assert refs["source_bindings_sha256"]
    # Mac 签出的源码清单与 Windows 将验证的 ZIP manifest.json 共用同一规范摘要。
    import hashlib
    import json

    manifest = refs["frame_source_manifest"]
    assert manifest["contract"] == "picotoo.frame-source-manifest.v1"
    assert manifest["bindings"] == refs["bindings"]
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == refs["source_bindings_sha256"]
    assert {
        (row["shot_id"], row["role"], row["asset_ref"], row["managed_sha256"])
        for row in refs["bindings"]
    } == {
        ("S01", "first", "maotai_master_v1", objects["maotai_master_v1"]),
        ("S01", "first", "backyard_v1", objects["backyard_v1"]),
        ("S02", "first", "maotai_master_v1", objects["maotai_master_v1"]),
    }
    assert "FRAME_WORKER_STAGING_AND_HASH_REQUIRED" in report["blocking_reasons"]
    assert report["can_queue"] is False
    assert report["can_generate"] is False
    assert _call(client, "/production-readiness", payload, owner).json() == report
    _assert_no_production(client)


@pytest.mark.parametrize("invalid_ref,expected_error", [
    ("C:\\\\private\\\\maotai.png", "FRAME_PATH_NOT_A_MANAGED_ID"),
    ("../../private/maotai.png", "FRAME_PATH_NOT_A_MANAGED_ID"),
    ("unknown_reference.png", "FRAME_REFERENCE_UNDECLARED_FOR_SHOT"),
])
def test_untrusted_first_frame_strings_never_become_worker_file_paths(
    context, invalid_ref, expected_error,
):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [invalid_ref]
    report = _call(client, "/production-readiness", payload, owner)
    assert report.status_code == 200, report.text
    parsed = report.json()
    assert parsed["checks"]["first_frame_mac_content_bound"] is False
    assert parsed["frame_reference_preview"]["frame_source_manifest"] is None
    assert any(
        reason.startswith(expected_error)
        for reason in parsed["blocking_reasons"]
    )
    assert parsed["can_queue"] is False
    _assert_no_production(client)


def test_duplicate_frame_ref_and_stale_master_bytes_cannot_pass(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "maotai_master_v1",
    ]
    duplicate = _call(client, "/production-readiness", payload, owner)
    assert duplicate.status_code == 200, duplicate.text
    assert any(
        reason.startswith("FRAME_DUPLICATE_REFERENCE")
        for reason in duplicate.json()["blocking_reasons"]
    )

    payload["completion"]["shots"][0]["first_frame"]["refs"] = ["maotai_master_v1"]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = ["maotai_master_v1"]
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered managed bytes")
    stale = _call(client, "/production-readiness", payload, owner)
    assert stale.status_code == 200, stale.text
    report = stale.json()
    assert report["checks"]["first_frame_mac_content_bound"] is False
    assert "FRAME_MASTER_CONTENT_UNVERIFIED" in report["blocking_reasons"]
    assert report["can_generate"] is False
    _assert_no_production(client)



def _issued_transfer(client, owner, objects):
    """Acquire a one-use download ticket through exact Owner and frame evidence."""
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "backyard_v1",
    ]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = [
        "maotai_master_v1",
    ]
    readiness = _call(client, "/production-readiness", payload, owner)
    assert readiness.status_code == 200, readiness.text
    source_sha = readiness.json()["frame_reference_preview"]["source_bindings_sha256"]
    assert source_sha
    issued = _call(
        client, "/frame-transfer/issue",
        {**payload, "expected_source_bindings_sha256": source_sha},
        owner,
    )
    assert issued.status_code == 200, issued.text
    return payload, issued.json()


def test_frame_ticket_streams_real_owner_bound_bytes_once_and_never_queues(
    context, tmp_path,
):
    from pathlib import Path
    import hashlib
    import requests

    from scripts.windows.fetch_frame_bundle import fetch_and_stage_frame_bundle

    client, owner, device, objects = context
    payload, issued = _issued_transfer(client, owner, objects)
    assert issued["status"] == "FRAME_TRANSFER_TICKET_ISSUED_DATA_ONLY"
    assert issued["can_queue"] is False
    assert issued["gpu_authorized"] is False

    class ResponseAdapter:
        def __init__(self, response):
            self.status_code = response.status_code
            self.headers = response.headers
            self.content = response.content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def iter_content(self, chunk_size):
            for offset in range(0, len(self.content), chunk_size):
                yield self.content[offset:offset + chunk_size]

    class SessionAdapter:
        def get(self, url, *, headers, stream, timeout, allow_redirects):
            # 下载器沿用旧设备令牌，但不持有 Owner Token。
            assert url == "http://127.0.0.1:8765/api/v1/studio/frame-transfer/download"
            assert stream is True and allow_redirects is False
            response = client.get(
                "/api/v1/studio/frame-transfer/download",
                headers={**headers, "Authorization": f"Bearer {device}"},
            )
            return ResponseAdapter(response)

    worker = tmp_path / "synthetic-windows-worker"
    worker.mkdir()
    (worker / "17_静态首帧板V2").mkdir()
    receipt = fetch_and_stage_frame_bundle(
        session=SessionAdapter(),
        core_url="http://127.0.0.1:8765",
        transfer_ticket=issued["ticket"],
        expected_source_bindings_sha256=issued["source_bindings_sha256"],
        expected_bundle_sha256=issued["bundle_sha256"],
        worker_root=worker,
    )
    assert receipt["status"] == "WINDOWS_BYTES_VERIFIED_NO_PRODUCTION_AUTHORITY"
    assert receipt["source_bindings_sha256"] == issued["source_bindings_sha256"]
    assert receipt["gpu_authorized"] is False
    assert receipt["can_queue"] is False
    assert receipt["worker_local_bytes_verified"] is True
    for item in receipt["bindings"]:
        on_worker = worker / "17_静态首帧板V2" / item["worker_ref"]
        assert hashlib.sha256(on_worker.read_bytes()).hexdigest() == item["managed_sha256"]

    # Ticket 已在首次 GET 时消费，即使是同一个受信任设备也不允许重播。
    replay = client.get(
        "/api/v1/studio/frame-transfer/download",
        headers={
            "Authorization": f"Bearer {device}",
            "X-Picotoo-Transfer-Ticket": issued["ticket"],
        },
    )
    assert replay.status_code == 409
    _assert_no_production(client)


def test_frame_transfer_rejects_wrong_device_plaintext_remote_and_owner_revoke(context):
    client, owner, device, objects = context
    payload, issued = _issued_transfer(client, owner, objects)
    path = "/api/v1/studio/frame-transfer/download"
    headers = {"X-Picotoo-Transfer-Ticket": issued["ticket"]}

    assert client.get(
        path, headers={**headers, "Authorization": f"Bearer {owner}"}
    ).status_code == 401
    assert client.get(
        path, headers={**headers, "Authorization": "Bearer incorrect"}
    ).status_code == 401

    # 伪造 X-Forwarded-Proto 的 HTTP 客户端不能越过 TLS 校验。
    assert client.get(
        path, headers={
            **headers, "Authorization": f"Bearer {device}",
            "X-Forwarded-Proto": "https",
        },
    ).status_code == 403
    remote = TestClient(
        client.app, base_url="http://core.example",
        client=("192.0.2.20", 45678),
    )
    assert remote.get(
        path, headers={**headers, "Authorization": f"Bearer {device}"}
    ).status_code == 403

    revoked = _call(
        client, "/revoke",
        {"subject_key": _SUBJECT, "review_id": payload["storyboard_review_id"]},
        owner,
    )
    assert revoked.status_code == 200
    assert client.get(
        path, headers={**headers, "Authorization": f"Bearer {device}"}
    ).status_code == 409
    _assert_no_production(client)


def test_frame_transfer_fails_closed_for_wrong_manifest_and_changed_managed_bytes(context):
    client, owner, device, objects = context
    payload, issued = _issued_transfer(client, owner, objects)
    invalid = _call(
        client, "/frame-transfer/issue",
        {**payload, "expected_source_bindings_sha256": "e" * 64},
        owner,
    )
    assert invalid.status_code == 409
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered after ticket creation")
    downloaded = client.get(
        "/api/v1/studio/frame-transfer/download",
        headers={
            "Authorization": f"Bearer {device}",
            "X-Picotoo-Transfer-Ticket": issued["ticket"],
        },
    )
    assert downloaded.status_code == 409
    _assert_no_production(client)


def test_frame_transfer_cannot_issue_without_scoped_owner_principal(context):
    client, owner, device, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = ["maotai_master_v1"]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = ["maotai_master_v1"]
    report = _call(client, "/production-readiness", payload, owner)
    expected = report.json()["frame_reference_preview"]["source_bindings_sha256"]
    assert expected

    assert _call(
        client, "/frame-transfer/issue",
        {**payload, "expected_source_bindings_sha256": expected},
        device,
    ).status_code == 403
    assert _call(
        client, "/frame-transfer/issue",
        {**payload, "expected_source_bindings_sha256": expected},
        "incorrect",
    ).status_code in (401, 403)
    _assert_no_production(client)



def test_real_loopback_http_socket_download_and_windows_sha_staging(context, tmp_path):
    """Use actual TCP HTTP and requests.Session, never a mocked HTTP response."""
    import socket
    import threading
    import time

    import requests
    import uvicorn

    from scripts.windows.fetch_frame_bundle import fetch_and_stage_frame_bundle

    client, owner, device, objects = context
    _, issued = _issued_transfer(client, owner, objects)

    # 使用 TestClient 已启动的 Mac Core 服务对象；Uvicorn 不再重复创建 SQLite。
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        client.app, host="127.0.0.1", port=port,
        lifespan="off", access_log=False, log_level="error",
    ))
    thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]),
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "local CPU-only HTTP server did not start"
        worker = tmp_path / "windows-socket-stage"
        worker.mkdir()
        (worker / "17_静态首帧板V2").mkdir()
        with requests.Session() as session:
            # 真正的 TCP 请求仅使用设备 Bearer，不泄露或复制 Owner Token。
            session.headers["Authorization"] = f"Bearer {device}"
            receipt = fetch_and_stage_frame_bundle(
                session=session,
                core_url=f"http://127.0.0.1:{port}",
                transfer_ticket=issued["ticket"],
                expected_source_bindings_sha256=issued["source_bindings_sha256"],
                expected_bundle_sha256=issued["bundle_sha256"],
                worker_root=worker,
            )
        assert receipt["worker_local_bytes_verified"] is True
        assert receipt["can_queue"] is False
        assert receipt["gpu_authorized"] is False
        # 只传输实际被 S01/S02 首帧引用的两种素材，而非整个资产库。
        assert set(receipt["worker_ref_paths_by_digest"]) == {
            objects["maotai_master_v1"], objects["backyard_v1"],
        }
        _assert_no_production(client)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), "local test socket must close cleanly"



@pytest.mark.parametrize("unsafe_url", [
    "http://192.0.2.20:8765",
    "http://core-on-lan.local:8765",
    "http://[",
    "https://operator:password@core.example",
    "https://core.example/path/to/private",
    "https://core.example/?token=secret",
])
def test_windows_frame_fetch_refuses_plaintext_or_ambiguous_remote_url(unsafe_url):
    from scripts.windows.fetch_frame_bundle import (
        FrameFetchError,
        _secure_core_url,
    )

    with pytest.raises(FrameFetchError, match="FRAME_FETCH_SECURE_CORE_URL_REQUIRED"):
        _secure_core_url(unsafe_url)
    assert _secure_core_url("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    assert _secure_core_url("https://core.example:8765") == "https://core.example:8765"



def test_asset_use_revocation_also_invalidates_unredeemed_transfer(context):
    client, owner, device, objects = context
    payload, issued = _issued_transfer(client, owner, objects)
    revoked = _call(
        client, "/asset-use/revoke",
        {"subject_key": _SUBJECT, "attestation_id": payload["attestation_id"]},
        owner,
    )
    assert revoked.status_code == 200, revoked.text
    response = client.get(
        "/api/v1/studio/frame-transfer/download",
        headers={
            "Authorization": f"Bearer {device}",
            "X-Picotoo-Transfer-Ticket": issued["ticket"],
        },
    )
    assert response.status_code == 409
    _assert_no_production(client)


def test_windows_fetch_refuses_https_when_session_disables_certificate_check(tmp_path):
    import requests

    from scripts.windows.fetch_frame_bundle import (
        FrameFetchError,
        fetch_and_stage_frame_bundle,
    )

    session = requests.Session()
    session.verify = False
    try:
        with pytest.raises(FrameFetchError, match="FRAME_FETCH_TLS_VERIFICATION_REQUIRED"):
            fetch_and_stage_frame_bundle(
                session=session, core_url="https://core.example",
                transfer_ticket="a" * 32,
                expected_source_bindings_sha256="b" * 64,
                expected_bundle_sha256="c" * 64,
                worker_root=tmp_path,
            )
    finally:
        session.close()



def test_paired_device_claims_pending_owner_frame_once_then_downloads(context):
    client, owner, device, objects = context
    endpoint = "/api/v1/studio/frame-transfer/claim"
    headers = {"Authorization": f"Bearer {device}"}

    # 不经过 Owner 审核不会存在任何可领取传输。
    assert client.post(endpoint, headers=headers).status_code == 204
    payload, issued = _issued_transfer(client, owner, objects)
    assert issued["can_queue"] is False
    claimed = client.post(endpoint, headers=headers)
    assert claimed.status_code == 200, claimed.text
    claim = claimed.json()
    assert claim["status"] == "FRAME_TRANSFER_CLAIMED_DATA_ONLY"
    assert claim["ticket"] == issued["ticket"]
    assert claim["source_bindings_sha256"] == issued["source_bindings_sha256"]
    assert claim["bundle_sha256"] == issued["bundle_sha256"]
    assert claim["can_queue"] is False
    assert claim["gpu_authorized"] is False
    assert claimed.headers["cache-control"] == "no-store"

    # 先领取者独占；单次下载后原 Ticket 不可重放。
    assert client.post(endpoint, headers=headers).status_code == 204
    downloaded = client.get(
        "/api/v1/studio/frame-transfer/download",
        headers={
            **headers, "X-Picotoo-Transfer-Ticket": claim["ticket"],
        },
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    replay = client.get(
        "/api/v1/studio/frame-transfer/download",
        headers={
            **headers, "X-Picotoo-Transfer-Ticket": claim["ticket"],
        },
    )
    assert replay.status_code == 409
    _assert_no_production(client)


def test_transfer_claim_denies_owner_token_remote_http_and_revoked_evidence(context):
    client, owner, device, objects = context
    endpoint = "/api/v1/studio/frame-transfer/claim"
    payload, _ = _issued_transfer(client, owner, objects)

    # Owner 不能代替已配对设备领取，远程明文 HTTP/伪造代理头必须阻止。
    assert client.post(
        endpoint, headers={"Authorization": f"Bearer {owner}"}
    ).status_code == 401
    remote = TestClient(
        client.app, base_url="http://mac.example",
        client=("192.0.2.30", 45678),
    )
    assert remote.post(
        endpoint, headers={"Authorization": f"Bearer {device}"}
    ).status_code == 403
    assert client.post(
        endpoint, headers={
            "Authorization": f"Bearer {device}",
            "X-Forwarded-Proto": "https",
        },
    ).status_code == 403

    revoked = _call(
        client, "/asset-use/revoke",
        {
            "subject_key": _SUBJECT,
            "attestation_id": payload["attestation_id"],
        },
        owner,
    )
    assert revoked.status_code == 200
    stale = client.post(
        endpoint, headers={"Authorization": f"Bearer {device}"},
    )
    assert stale.status_code == 409
    assert client.post(
        endpoint, headers={"Authorization": f"Bearer {device}"},
    ).status_code == 204
    _assert_no_production(client)



def _owner_freeze_payload(client, owner, objects):
    """Prepare a full synthetically approved source/episode pair for held Job freezing."""
    reviewed = _create_reviewed_candidate(client, owner, objects)
    reviewed["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "backyard_v1",
    ]
    reviewed["completion"]["shots"][1]["first_frame"]["refs"] = [
        "maotai_master_v1",
    ]
    preview = _call(client, "/production-readiness", reviewed, owner)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["checks"]["storyboard_review_current"] is True
    assert result["checks"]["asset_use_attestation_current"] is True
    assert result["checks"]["first_frame_mac_content_bound"] is True
    return {
        **reviewed,
        "expected_candidate_episode_sha256": result["candidate_episode_sha256"],
        "expected_source_bindings_sha256":
            result["frame_reference_preview"]["source_bindings_sha256"],
        "confirm_gpu_hold": True,
    }


def test_owner_freeze_creates_exact_held_tasks_audit_and_idempotency(context):
    client, owner, device, objects = context
    payload = _owner_freeze_payload(client, owner, objects)
    assert client.app.state.services.owner_mode_gpu_hold is True
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM production_episodes"
    ) == 0

    freeze = _call(client, "/production-freeze", payload, owner)
    assert freeze.status_code == 200, freeze.text
    result = freeze.json()
    assert result["status"] == "FROZEN_OWNER_INTENT_AWAITING_INDEPENDENT_ADMISSION"
    assert result["frozen_plan_sha256"]
    assert result["core_task_records_created"] is True
    assert result["already_frozen"] is False
    assert result["can_lease"] is False
    assert result["gpu_authorized"] is False
    assert result["master_rights_independently_verified"] is False
    assert result["worker_local_bytes_verified"] is False
    assert len(result["tasks"]) == 6
    assert [item["shot_id"] for item in result["tasks"]] == [
        "S01", "S01", "S01", "S02", "S02", "S02",
    ]
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM tasks"
    ) == 6
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM approvals"
    ) == 0
    rows = client.app.state.services.database.fetchall(
        "SELECT action, decision, reason_code, details_redacted_json "
        "FROM audit_events WHERE resource_id=? AND action='episode.freeze_owner_hold'",
        (result["episode_id"],),
    )
    assert len(rows) == 1
    assert rows[0]["decision"] == "FROZEN_HOLD"
    assert rows[0]["reason_code"] == "MASTER_WORKER_GPU_NOT_ADMITTED"
    import json
    assert json.loads(rows[0]["details_redacted_json"])[
        "frozen_plan_sha256"
    ] == result["frozen_plan_sha256"]

    # 新的真实 Task 行虽然已冻结到 SQLite，却没有任意 GPU lease 权限。
    lease = client.post(
        "/api/v1/executors/lease",
        json={
            "worker_id": "win-worker-test",
            "resource_tags": ["gpu-5070ti"],
            "lease_seconds": 90,
        },
        headers={"Authorization": f"Bearer {device}"},
    )
    assert lease.status_code == 204
    again = _call(client, "/production-freeze", payload, owner)
    assert again.status_code == 200, again.text
    assert again.json()["already_frozen"] is True
    assert again.json()["tasks"] == result["tasks"]
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM tasks"
    ) == 6
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events "
        "WHERE action='episode.freeze_owner_hold'"
    ) == 1


@pytest.mark.parametrize("mutation,expected", [
    ("episode_sha", "FROZEN_PLAN_EPISODE_SHA_STALE"),
    ("frame_sha", "FROZEN_PLAN_FRAME_SOURCE_STALE"),
    ("episode_invalid", "EPISODE_SHOT_ORDER_OR_ID_DRIFT"),
    ("budget", "FROZEN_PLAN_EPISODE_BUDGET_EXCEEDED"),
    ("revoked_storyboard", "OWNER_STORYBOARD_REVIEW_REVOKED"),
    ("revoked_asset", "ASSET_USE_ATTESTATION_REVOKED"),
    ("changed_source", "FROZEN_PLAN"),
])
def test_owner_freeze_rejects_stale_evidence_without_any_job(context, mutation, expected):
    client, owner, _, objects = context
    payload = _owner_freeze_payload(client, owner, objects)
    if mutation == "episode_sha":
        payload["expected_candidate_episode_sha256"] = "f" * 64
    elif mutation == "frame_sha":
        payload["expected_source_bindings_sha256"] = "f" * 64
    elif mutation == "episode_invalid":
        payload["completion"]["shots"][1]["shot_id"] = "S99"
    elif mutation == "budget":
        payload["completion"]["shots"][0]["video"]["seeds"] = list(range(9))
        # 单独验证预算门禁：更改 Episode 后先重新计算正确内容摘要。
        # 不然会先被更早的 SHA 防篡改门禁拒绝，无法测到预算本身。
        from picotoopet_core.domain.storypack import StoryPackV1
        from picotoopet_core.domain.storypack_episode_candidate import (
            complete_storypack_episode_preview,
        )
        candidate = complete_storypack_episode_preview(
            StoryPackV1.model_validate(payload["storypack"]),
            payload["storypack_sha256"],
            payload["completion"],
        )
        payload["expected_candidate_episode_sha256"] = candidate[
            "candidate_episode_sha256"
        ]
    elif mutation == "revoked_storyboard":
        assert _call(client, "/revoke", {
            "subject_key": _SUBJECT,
            "review_id": payload["storyboard_review_id"],
        }, owner).status_code == 200
    elif mutation == "revoked_asset":
        assert _call(client, "/asset-use/revoke", {
            "subject_key": _SUBJECT,
            "attestation_id": payload["attestation_id"],
        }, owner).status_code == 200
    elif mutation == "changed_source":
        digest = objects["maotai_master_v1"]
        root = client.app.state.services.settings.paths.objects_dir
        (root / digest[:2] / digest[2:]).write_bytes(b"tampered")
    response = _call(client, "/production-freeze", payload, owner)
    assert response.status_code in (409, 422), response.text
    assert expected in response.text or mutation == "changed_source", response.text
    _assert_no_production(client)


def test_owner_frozen_plan_never_accepts_device_or_remote_owner(context):
    client, owner, device, objects = context
    payload = _owner_freeze_payload(client, owner, objects)
    assert _call(client, "/production-freeze", payload, device).status_code == 403
    from fastapi.testclient import TestClient
    remote = TestClient(client.app, base_url="http://mac.example",
                        client=("192.0.2.40", 48000))
    result = remote.post(
        _ROOT + "/production-freeze",
        json=payload,
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert result.status_code == 403
    invalid = {**payload, "confirm_gpu_hold": False}
    assert _call(client, "/production-freeze", invalid, owner).status_code == 422
    _assert_no_production(client)


def test_frozen_plan_cannot_mutate_same_episode_source_or_owner_review(context):
    client, owner, _, objects = context
    payload = _owner_freeze_payload(client, owner, objects)
    initial = _call(client, "/production-freeze", payload, owner)
    assert initial.status_code == 200, initial.text
    original = initial.json()["frozen_plan_sha256"]
    assert original

    # 保持同一 Episode ID 和像素时，仍不能替换 Owner 审核身份来源。
    from copy import deepcopy
    changed = deepcopy(payload)
    changed["storyboard_review_id"] = "fake-review-id"
    blocked = _call(client, "/production-freeze", changed, owner)
    assert blocked.status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events "
        "WHERE action='episode.freeze_owner_hold'"
    ) == 1
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM tasks"
    ) == 6


def _master_review_payload(held: dict, original_owner_claims: list[dict]) -> dict:
    """Build only synthetic human-review evidence from exactly frozen source IDs."""
    return {
        "episode_id": held["episode_id"],
        "frozen_plan_sha256": held["frozen_plan_sha256"],
        "source_bindings_sha256": held["source_bindings_sha256"],
        "confirm_independent_human_review": True,
        "claims": [
            {
                "ref": claim["ref"],
                "asset_sha256": claim["asset_sha256"],
                "basis": claim["basis"],
                # 自行创作的合成源文件本身作为原始证据；并非法律证明。
                "evidence_ref": claim["ref"],
                "evidence_sha256": claim["asset_sha256"],
                "human_source_review_completed": True,
                "commercial_ai_use_checked": True,
            }
            for claim in original_owner_claims
        ],
    }


def _master_call(client, suffix, payload: dict, credential: str):
    return client.post(
        "/api/v1/studio/storypacks/master-review/" + suffix,
        json=payload, headers={"Authorization": f"Bearer {credential}"},
    )


def test_independent_master_review_uses_real_frozen_sqlite_and_stays_gpu_held(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    freeze = _call(client, "/production-freeze", source, owner)
    assert freeze.status_code == 200, freeze.text
    payload = _master_review_payload(freeze.json(), source["claims"])
    master = client.app.state.synthetic_master_token

    # Owner 与普通设备均不可自称独立 MASTER 审核人。
    assert _master_call(client, "commit", payload, owner).status_code == 403
    assert _master_call(client, "commit", payload, device).status_code == 403
    reviewed = _master_call(client, "commit", payload, master)
    assert reviewed.status_code == 200, reviewed.text
    result = reviewed.json()
    assert result["status"] == "INDEPENDENT_HUMAN_MASTER_REVIEW_GPU_HOLD"
    assert result["gpu_authorized"] is False
    assert result["can_lease"] is False
    assert result["independent_human_source_review_recorded"] is True
    assert len(result["master_review_id"]) > 10

    repeated = _master_call(client, "commit", payload, master)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["master_review_id"] == result["master_review_id"]
    assert repeated.json()["already_reviewed"] is True
    verified = _master_call(
        client, "verify", {**payload, "master_review_id": result["master_review_id"]},
        master,
    )
    assert verified.status_code == 200, verified.text
    # 即使两个独立身份都审核过，旧 Device 路由也不能领取 GPU 任务。
    assert client.post(
        "/api/v1/executors/lease",
        json={"worker_id": "win-worker", "resource_tags": ["gpu-5070ti"],
              "lease_seconds": 90},
        headers={"Authorization": f"Bearer {device}"},
    ).status_code == 204
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='studio.storypack.master_source.review'"
    ) == 1


def test_independent_master_rejects_cross_plan_and_tampered_source(context):
    client, owner, _, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    held = _call(client, "/production-freeze", source, owner).json()
    master = client.app.state.synthetic_master_token
    payload = _master_review_payload(held, source["claims"])

    wrong = {**payload, "frozen_plan_sha256": "f" * 64}
    assert _master_call(client, "commit", wrong, master).status_code == 409
    incomplete = copy.deepcopy(payload)
    incomplete["claims"].pop()
    assert _master_call(client, "commit", incomplete, master).status_code == 409
    mismatched = copy.deepcopy(payload)
    mismatched["claims"][0]["asset_sha256"] = "e" * 64
    assert _master_call(client, "commit", mismatched, master).status_code == 409

    reviewed = _master_call(client, "commit", payload, master)
    assert reviewed.status_code == 200, reviewed.text
    review_id = reviewed.json()["master_review_id"]
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"changed")
    assert _master_call(
        client, "verify", {**payload, "master_review_id": review_id}, master,
    ).status_code == 409


def test_independent_master_review_revocation_blocks_future_validation(context):
    client, owner, _, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    held = _call(client, "/production-freeze", source, owner).json()
    master = client.app.state.synthetic_master_token
    payload = _master_review_payload(held, source["claims"])
    review = _master_call(client, "commit", payload, master)
    assert review.status_code == 200, review.text
    review_id = review.json()["master_review_id"]
    revoked = _master_call(
        client, "revoke", {"episode_id": held["episode_id"],
                          "master_review_id": review_id}, master,
    )
    assert revoked.status_code == 200, revoked.text
    assert _master_call(
        client, "verify", {**payload, "master_review_id": review_id}, master,
    ).status_code == 409
    assert _master_call(client, "commit", payload, master).status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='studio.storypack.master_source.revoke'"
    ) == 1


def _staged_core_report(client, owner, source, episode_id="MAOTAI_READINESS"):
    """Construct a synthetic Windows Studio statement using Core's exact source contract."""
    # Freeze payload has three additional fields forbidden by strict readiness schema.
    readiness = {
        key: value for key, value in source.items()
        if key not in (
            "expected_candidate_episode_sha256",
            "expected_source_bindings_sha256",
            "confirm_gpu_hold",
        )
    }
    preview = _call(client, "/production-readiness", readiness, owner)
    assert preview.status_code == 200, preview.text
    reference = preview.json()["frame_reference_preview"]
    return {
        "episode_id": episode_id,
        "source_bindings_sha256": reference["source_bindings_sha256"],
        "storypack_sha256": reference["storypack_sha256"],
        "owner_subject_sha256": reference["owner_subject_sha256"],
        "bindings": reference["bindings"],
        "verified_bytes": 150,
        "worker_local_bytes_verified": True,
    }


def _post_staged_core(client, payload, token, *, client_path=None):
    return client.post(
        client_path or "/api/v1/studio/frame-transfer/staging-report",
        json=payload, headers={"Authorization": f"Bearer {token}"},
    )


def test_windows_stage_report_matches_real_frozen_plan_and_cannot_lease(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    body = _staged_core_report(client, owner, source)

    # Copying files before Owner freezes an Episode cannot manufacture a Plan.
    early = _post_staged_core(client, body, device)
    assert early.status_code == 200, early.text
    assert early.json()["core_staging_linked"] is False
    assert early.json()["gpu_authorized"] is False
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.windows_staging_report'"
    ) == 0

    frozen = _call(client, "/production-freeze", source, owner)
    assert frozen.status_code == 200, frozen.text
    linked = _post_staged_core(client, body, device)
    assert linked.status_code == 200, linked.text
    receipt = linked.json()
    assert receipt["status"] == "WINDOWS_STAGING_REPORTED_FOR_FROZEN_PLAN"
    assert receipt["frozen_plan_sha256"] == frozen.json()["frozen_plan_sha256"]
    assert receipt["worker_independently_verified"] is False
    assert receipt["can_lease"] is False
    assert receipt["gpu_authorized"] is False

    again = _post_staged_core(client, body, device)
    assert again.status_code == 200, again.text
    assert again.json()["already_reported"] is True
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.windows_staging_report'"
    ) == 1
    assert client.post(
        "/api/v1/executors/lease",
        json={"worker_id": "win-worker", "resource_tags": ["gpu-5070ti"],
              "lease_seconds": 90},
        headers={"Authorization": f"Bearer {device}"},
    ).status_code == 204


def test_windows_stage_report_rejects_mismatched_shots_mac_tamper_and_owner_token(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    assert _call(client, "/production-freeze", source, owner).status_code == 200
    body = _staged_core_report(client, owner, source)

    # Neither Owner Bearer nor missing credentials can masquerade as the paired device.
    assert _post_staged_core(client, body, owner).status_code == 401
    assert client.post(
        "/api/v1/studio/frame-transfer/staging-report", json=body
    ).status_code == 401

    for field in ("source_bindings_sha256", "storypack_sha256", "owner_subject_sha256"):
        altered = copy.deepcopy(body)
        altered[field] = "f" * 64
        assert _post_staged_core(client, altered, device).status_code == 409
    altered = copy.deepcopy(body)
    altered["bindings"][0]["shot_id"] = "WRONG"
    assert _post_staged_core(client, altered, device).status_code == 409
    altered = copy.deepcopy(body)
    altered["bindings"] = altered["bindings"][:-1]
    assert _post_staged_core(client, altered, device).status_code == 409
    altered = copy.deepcopy(body)
    altered["bindings"].append(copy.deepcopy(altered["bindings"][0]))
    assert _post_staged_core(client, altered, device).status_code == 409
    altered = copy.deepcopy(body)
    altered["worker_local_bytes_verified"] = False
    assert _post_staged_core(client, altered, device).status_code == 422
    altered = copy.deepcopy(body)
    altered["worker_ref"] = r"C:\private\dog.png"
    assert _post_staged_core(client, altered, device).status_code == 422

    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered")
    assert _post_staged_core(client, body, device).status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.windows_staging_report'"
    ) == 0


def _signed_worker_proof(challenge: dict, key: str = "w" * 48) -> dict:
    """Sign the canonical Core challenge with the separate synthetic Worker key."""
    import hashlib
    import hmac
    import json
    fields = (
        "nonce", "worker_id", "episode_id", "frozen_plan_sha256",
        "source_bindings_sha256", "bindings_sha256",
    )
    message = {
        "contract": "picotoo.worker-local-sha-proof.v1",
        **{name: challenge[name] for name in fields},
    }
    encoded = json.dumps(
        message, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    signature = hmac.new(
        key.encode("ascii"),
        hashlib.sha256(encoded).hexdigest().encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {**message, "signature": signature}


def _worker_proof_post(client, name, payload, device):
    return client.post(
        f"/api/v1/studio/worker-proof/{name}", json=payload,
        headers={"Authorization": f"Bearer {device}"},
    )


def test_worker_hmac_proof_frozen_stage_and_no_gpu_lease(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    held = _call(client, "/production-freeze", source, owner)
    assert held.status_code == 200
    # 未接收到 Windows 暂存数据前，不允许任何独立 Worker 挑战。
    absent = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert absent.status_code == 204

    staging = _staged_core_report(client, owner, source)
    assert _post_staged_core(client, staging, device).status_code == 200
    assert _worker_proof_post(client, "claim", {"worker_id": "different-worker"}, device).status_code == 409
    challenge = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert challenge.status_code == 200, challenge.text
    offered = challenge.json()
    assert offered["frozen_plan_sha256"] == held.json()["frozen_plan_sha256"]
    assert len(offered["bindings"]) == len(staging["bindings"])
    assert offered["can_lease"] is False and offered["gpu_authorized"] is False

    wrong = _signed_worker_proof(offered, "z" * 48)
    assert _worker_proof_post(client, "submit", wrong, device).status_code == 409
    assert _worker_proof_post(client, "submit", _signed_worker_proof(offered), device).status_code == 409
    renewed = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert renewed.status_code == 200, renewed.text
    signed = _signed_worker_proof(renewed.json())
    accepted = _worker_proof_post(client, "submit", signed, device)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["status"] == "WORKER_HMAC_SOURCE_REPORT_ACCEPTED_GPU_HOLD"
    assert receipt["worker_authenticated"] is True
    assert receipt["hardware_attestation"] is False
    assert receipt["can_lease"] is False
    assert receipt["gpu_authorized"] is False
    assert _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device).status_code == 204
    assert _worker_proof_post(client, "submit", signed, device).status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.worker_local_proof'"
    ) == 1
    assert client.post(
        "/api/v1/executors/lease",
        json={"worker_id": "win-worker-test", "resource_tags": ["gpu-5070ti"],
              "lease_seconds": 90},
        headers={"Authorization": f"Bearer {device}"},
    ).status_code == 204


def test_worker_proof_rejects_different_plan_and_later_tampered_mac_source(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    assert _call(client, "/production-freeze", source, owner).status_code == 200
    staging = _staged_core_report(client, owner, source)
    assert _post_staged_core(client, staging, device).status_code == 200
    offered = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert offered.status_code == 200
    wrong = _signed_worker_proof(offered.json())
    wrong["frozen_plan_sha256"] = "f" * 64
    assert _worker_proof_post(client, "submit", wrong, device).status_code == 409

    good = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert good.status_code == 200
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"changed after staging")
    assert _worker_proof_post(
        client, "submit", _signed_worker_proof(good.json()), device,
    ).status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.worker_local_proof'"
    ) == 0


def test_worker_hmac_key_actually_loads_and_is_redacted(monkeypatch, tmp_path):
    """Real Mac Core loader must accept one-time opt-in, never expose the shared key."""
    from picotoopet_core.config.loader import load_settings
    from pydantic import ValidationError

    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("PICOTOO_API_TOKEN", "synthetic_mac_core_token_0123456789")
    monkeypatch.setenv("PICOTOO_WORKER_ATTEST_ID", "win-worker-test")
    monkeypatch.setenv("PICOTOO_WORKER_ATTEST_KEY", "w" * 48)
    settings = load_settings()
    assert settings.worker_attestation_id == "win-worker-test"
    assert settings.worker_attestation_key == "w" * 48
    report = settings.redacted_dict()
    assert report["worker_attestation_key"] == "***REDACTED***"
    assert "w" * 48 not in str(report)

    monkeypatch.delenv("PICOTOO_WORKER_ATTEST_ID")
    with pytest.raises(ValidationError):
        load_settings()
    monkeypatch.delenv("PICOTOO_WORKER_ATTEST_KEY")
    settings = load_settings()
    assert settings.worker_attestation_key is None


def _prepare_scoped_gpu_admission(context):
    """Full synthetic Owner -> MASTER -> stage -> Worker HMAC -> held task proof."""
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    frozen = _call(client, "/production-freeze", source, owner)
    assert frozen.status_code == 200, frozen.text
    held = frozen.json()
    staged = _staged_core_report(client, owner, source)
    assert _post_staged_core(client, staged, device).status_code == 200

    master = client.app.state.synthetic_master_token
    master_claim = _master_review_payload(held, source["claims"])
    reviewed = _master_call(client, "commit", master_claim, master)
    assert reviewed.status_code == 200, reviewed.text

    claimed = _worker_proof_post(client, "claim", {"worker_id": "win-worker-test"}, device)
    assert claimed.status_code == 200, claimed.text
    signed = _signed_worker_proof(claimed.json())
    proof = _worker_proof_post(client, "submit", signed, device)
    assert proof.status_code == 200, proof.text
    return held, reviewed.json()["master_review_id"]


def _owner_admit(client, owner, held, master_review_id):
    return client.post(
        "/api/v1/studio/storypacks/production-admission/commit",
        json={
            "episode_id": held["episode_id"],
            "frozen_plan_sha256": held["frozen_plan_sha256"],
            "master_review_id": master_review_id,
            "confirm_one_frozen_episode_gpu_admission": True,
        },
        headers={"Authorization": f"Bearer {owner}"},
    )


def _signed_scoped_lease(challenge, secret="w" * 48):
    """Build exactly the same one-use Worker lease signature as executor_bridge."""
    import hashlib
    import hmac
    import json
    fields = (
        "contract", "nonce", "worker_id", "episode_id", "task_id",
        "frozen_plan_sha256", "resource_tags", "lease_seconds", "resume_task_id",
    )
    content = {key: challenge[key] for key in fields}
    serialized = json.dumps(
        content, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hmac.new(
        secret.encode("ascii"),
        hashlib.sha256(serialized).hexdigest().encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _scoped_lease_offer(client, device, *, resume=None):
    body = {
        "worker_id": "win-worker-test",
        "resource_tags": ["gpu-5070ti"],
        "lease_seconds": 90,
        "resume_task_id": resume,
    }
    offer = client.post(
        "/api/v1/studio/production-admission/lease-challenge", json=body,
        headers={"Authorization": f"Bearer {device}"},
    )
    return body, offer


def _scoped_lease_claim(client, device, body, offer, *, secret="w" * 48):
    return client.post(
        "/api/v1/executors/lease", json=body,
        headers={
            "Authorization": f"Bearer {device}",
            "X-Picotoo-Admission-Nonce": offer["nonce"],
            "X-Picotoo-Admission-HMAC": _signed_scoped_lease(offer, secret),
        },
    )


def test_exact_scoped_lease_requires_live_owner_master_worker_and_signed_task(context):
    client, owner, device, _ = context
    held, master_id = _prepare_scoped_gpu_admission(context)
    ordinary = client.post(
        "/api/v1/executors/lease",
        json={"worker_id": "win-worker-test", "resource_tags": ["gpu-5070ti"],
              "lease_seconds": 90},
        headers={"Authorization": f"Bearer {device}"},
    )
    assert ordinary.status_code == 204
    admitted = _owner_admit(client, owner, held, master_id)
    assert admitted.status_code == 200, admitted.text
    admission = admitted.json()
    assert admission["gpu_authorized_for_exact_episode"] is True
    assert admission["local_gpu_submitted"] is False

    body, offered = _scoped_lease_offer(client, device)
    assert offered.status_code == 200, offered.text
    chosen = offered.json()
    assert chosen["episode_id"] == held["episode_id"]
    assert chosen["frozen_plan_sha256"] == held["frozen_plan_sha256"]
    assert chosen["task_id"] == held["tasks"][0]["task_id"]

    wrong = _scoped_lease_claim(client, device, body, chosen, secret="z" * 48)
    assert wrong.status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM tasks WHERE status='Running'"
    ) == 0
    # Replay after a failed HMAC is invalid: challenge is one-use.
    assert _scoped_lease_claim(client, device, body, chosen).status_code == 409
    body, offered = _scoped_lease_offer(client, device)
    assert offered.status_code == 200
    lease = _scoped_lease_claim(client, device, body, offered.json())
    assert lease.status_code == 200, lease.text
    task = lease.json()
    assert task["task_id"] == chosen["task_id"]
    assert task["status"] == "Running"
    assert task["attempt_count"] == 1
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.scoped_gpu_lease_granted'"
    ) == 1

    # Existing lease owner can heartbeat. No other queue is silently admitted.
    alive = client.post(
        f"/api/v1/tasks/{task['task_id']}/heartbeat",
        json={"worker_id": "win-worker-test", "attempt_count": 1,
              "progress": 0.02, "message": "signed Worker CPU-only test"},
        headers={"Authorization": f"Bearer {device}"},
    )
    assert alive.status_code == 200, alive.text

    revoked = client.post(
        "/api/v1/studio/storypacks/production-admission/revoke",
        json={"episode_id": held["episode_id"],
              "admission_id": admission["admission_id"]},
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert revoked.status_code == 200, revoked.text
    assert _scoped_lease_offer(client, device)[1].status_code == 204
    assert client.post(
        f"/api/v1/tasks/{task['task_id']}/heartbeat",
        json={"worker_id": "win-worker-test", "attempt_count": 1,
              "progress": 0.03, "message": "revoked"},
        headers={"Authorization": f"Bearer {device}"},
    ).status_code == 409
    assert _owner_admit(client, owner, held, master_id).status_code == 409


def test_scoped_admission_denies_missing_master_and_bad_actor(context):
    client, owner, device, objects = context
    source = _owner_freeze_payload(client, owner, objects)
    frozen = _call(client, "/production-freeze", source, owner)
    assert frozen.status_code == 200
    held = frozen.json()
    missing_master = _owner_admit(client, owner, held, "missing-master-id")
    assert missing_master.status_code == 409
    assert _owner_admit(client, device, held, "missing-master-id").status_code in (401, 403)
    assert _scoped_lease_offer(client, device)[1].status_code == 204
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.scoped_gpu_admission'"
    ) == 0


def test_scoped_lease_rejects_old_resume_and_cross_episode(context):
    client, owner, device, _ = context
    held, master_id = _prepare_scoped_gpu_admission(context)
    admitted = _owner_admit(client, owner, held, master_id)
    assert admitted.status_code == 200, admitted.text
    assert _scoped_lease_offer(client, device, resume="legacy-task")[1].status_code == 204
    body, offer = _scoped_lease_offer(client, device)
    assert offer.status_code == 200
    changed_body = {**body, "resume_task_id": "legacy-task"}
    assert _scoped_lease_claim(
        client, device, changed_body, offer.json(),
    ).status_code == 409
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM tasks WHERE status='Running'"
    ) == 0


def test_protected_owner_mode_stays_closed_without_explicit_runtime_enable(context):
    client, owner, device, _ = context
    held, master_id = _prepare_scoped_gpu_admission(context)
    # Running a prebuilt release without the explicit opt-in remains GPU-HOLD.
    from picotoopet_core.config.models import AppSettings
    services = client.app.state.services
    original = services.settings
    services.settings = original.model_copy(update={"scoped_gpu_admission_enabled": False})
    try:
        assert _owner_admit(client, owner, held, master_id).status_code == 409
        assert _scoped_lease_offer(client, device)[1].status_code == 204
        assert client.post(
            "/api/v1/executors/lease",
            json={"worker_id": "win-worker-test", "resource_tags": ["gpu-5070ti"],
                  "lease_seconds": 90},
            headers={"Authorization": f"Bearer {device}"},
        ).status_code == 204
    finally:
        services.settings = original


def test_scoped_admission_rederives_video_prompt_and_seed_from_frozen_episode(context):
    client, owner, device, _ = context
    held, master_id = _prepare_scoped_gpu_admission(context)
    svc = client.app.state.services
    # 攻击者只能改动 SQLite 旧任务内容，不能修改 Owner 原始冻结 Episode。
    with svc.database.transaction() as db:
        row = db.execute(
            "SELECT task_id, payload_json FROM tasks WHERE task_type='gen.video' "
            "AND json_extract(payload_json,'$.episode_id')=? ORDER BY rowid LIMIT 1",
            (held["episode_id"],),
        ).fetchone()
        altered = json.loads(row["payload_json"])
        altered["jobs"]["jobs"][0]["prompt"] = "unreviewed arbitrary replacement"
        db.execute(
            "UPDATE tasks SET payload_json=? WHERE task_id=?",
            (json.dumps(altered), row["task_id"]),
        )
    # 仅比较首帧 SHA 并不足够，必须验证视频 prompt/seed 也和冻结 Episode 一致。
    rejected = _owner_admit(client, owner, held, master_id)
    assert rejected.status_code == 409, rejected.text
    assert _scoped_lease_offer(client, device)[1].status_code == 204
    assert svc.database.scalar(
        "SELECT COUNT(*) FROM audit_events WHERE action='episode.scoped_gpu_admission'"
    ) == 0
