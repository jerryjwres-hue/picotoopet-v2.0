"""Mac-local Owner review CLI: provisioning and loopback review, no secret leakage."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
from pathlib import Path

import pytest

from picotoopet_core.autonomous.owner_structured_review import (
    OwnerStructuredReviewCommitRequest,
    OwnerStructuredReviewPreviewRequest,
)
from picotoopet_core.security.owner_principal import OwnerReviewRegistry

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "mac" / "owner_review" / "owner_review_local.py"
spec = importlib.util.spec_from_file_location("owner_review_local", SCRIPT)
cli = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(cli)

GOAL = "510f38c9-e30d-4ff6-9f8a-0273f81c6afc"
D = "d" * 64


class FakeKeychain:
    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.argv_seen: list[list[str]] = []

    def store(self, service: str, secret: str) -> None:
        self.items[service] = secret

    def read(self, service: str) -> str | None:
        return self.items.get(service)


def _proposal(**overrides):
    fields = {
        path: {"field_path": path, "status": "EXPLICIT", "value": "v", "evidence_id": "e1",
               "authority_kind": None, "value_digest": D}
        for path in cli.REQUIRED_FIELD_PATHS
    }
    fields["subject_lock.distinguishing_marks"] = {
        "field_path": "subject_lock.distinguishing_marks", "status": "UNKNOWN",
        "value": None, "evidence_id": None, "authority_kind": None, "value_digest": None,
    }
    document = {
        "schema_version": "owner_structured_review.proposal.v1", "goal_id": GOAL,
        "creative_job_id": "d70e9d51-5a33-42cb-a560-30e596ca6d08",
        "review_actor_id": "owner-dsfed", "registry_revision": 1, "subject_key": "pet:maotai",
        "creative_profile": "creative.content_plan.v2", "source_set_digest": D,
        "objective_digest": D, "source_revision_digest": "a" * 64, "source_evidence": [],
        "fields": fields, "proposal_digest": "b" * 64,
    }
    document.update(overrides)
    return document


class FakeApi:
    def __init__(self, proposal, outcome="READY") -> None:
        self.proposal = proposal
        self.outcome = outcome
        self.calls: list[tuple[str, str, dict | None, dict]] = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        if url.endswith("/proposal"):
            return self.proposal
        if url.endswith("/preview"):
            OwnerStructuredReviewPreviewRequest.model_validate(body)
            return {"goal_id": GOAL, "outcome": self.outcome, "reason_codes": [] if self.outcome == "READY"
                    else ["OWNER_REVIEW_FIELD_UNKNOWN:subject_lock.distinguishing_marks"],
                    "source_revision_digest": "a" * 64, "review_digest": "c" * 64,
                    "preview_digest": "e" * 64, "state_facts": None}
        if url.endswith("/commit"):
            OwnerStructuredReviewCommitRequest.model_validate(body)
            return {"commitment_id": "commit-1", "facts_id": "facts-1", "goal_id": GOAL}
        raise AssertionError(url)


def _answers(*values):
    queue = list(values)
    return lambda prompt="": queue.pop(0)


# ── provisioning ──────────────────────────────────────────────────────────────


def test_provision_stores_secret_only_in_keychain_and_writes_private_registry(tmp_path):
    keychain, out = FakeKeychain(), io.StringIO()
    registry = tmp_path / "owner-review-registry.json"
    cli.provision(registry_path=registry, credential_id="owner-maotai-1", actor_id="owner-dsfed",
                  subject_keys=["pet:maotai"], keychain=keychain, out=out)

    secret = keychain.items["PicotooPetV2.OwnerReview.owner-maotai-1"]
    assert len(secret) >= 43 and secret not in out.getvalue()
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    parsed = OwnerReviewRegistry.model_validate_json(registry.read_bytes())
    grant = parsed.credentials[0]
    assert grant.token_sha256 == hashlib.sha256(secret.encode()).hexdigest()
    assert grant.subject_keys == ("pet:maotai",) and grant.permissions == ("owner_facts.review",)
    assert grant.enabled and grant.registry_revision == 1
    assert secret not in registry.read_text()


def test_reprovision_rotates_secret_and_bumps_revision(tmp_path):
    keychain, registry = FakeKeychain(), tmp_path / "r.json"
    for _ in range(2):
        cli.provision(registry_path=registry, credential_id="owner-maotai-1", actor_id="owner-dsfed",
                      subject_keys=["pet:maotai"], keychain=keychain, out=io.StringIO())
    grants = OwnerReviewRegistry.model_validate_json(registry.read_bytes()).credentials
    assert len(grants) == 1 and grants[0].registry_revision == 2


@pytest.mark.parametrize("subject", ["pet:*", "maotai", "pet:Maotai"])
def test_provision_rejects_wildcard_or_malformed_subject(tmp_path, subject):
    with pytest.raises(SystemExit):
        cli.provision(registry_path=tmp_path / "r.json", credential_id="c1", actor_id="a1",
                      subject_keys=[subject], keychain=FakeKeychain(), out=io.StringIO())


def test_keychain_secret_is_written_through_stdin_not_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["input"] = argv, kwargs.get("input")

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli.MacKeychain().store("PicotooPetV2.OwnerReview.c1", "S" * 43)
    assert "S" * 43 not in " ".join(seen["argv"]) and "S" * 43 in seen["input"]


# ── review ────────────────────────────────────────────────────────────────────


def _keychain_with_token():
    keychain = FakeKeychain()
    keychain.items["PicotooPetV2.OwnerReview.owner-maotai-1"] = "T" * 43
    return keychain


def test_review_confirms_explicit_asks_unknown_and_commits_only_after_phrase():
    api, out = FakeApi(_proposal()), io.StringIO()
    # distinguishing_marks: correct with a JSON list; no static opt-in; then the phrase.
    result = cli.review(goal_id=GOAL, base_url="http://127.0.0.1:8765", credential_id="owner-maotai-1",
                        keychain=_keychain_with_token(), http=api,
                        ask=_answers("x", '["white mask"]', "n", "确认提交"), out=out)
    assert result == 0
    methods = [(m, u.rsplit("/", 1)[-1]) for m, u, _, _ in api.calls]
    assert methods == [("GET", "proposal"), ("POST", "preview"), ("POST", "commit")]
    preview_body = api.calls[1][2]
    decisions = {d["field_path"]: d for d in preview_body["decisions"]}
    assert decisions["subject_lock.species"]["decision"] == "CONFIRM"
    assert decisions["subject_lock.distinguishing_marks"] == {
        "field_path": "subject_lock.distinguishing_marks", "decision": "CORRECT",
        "corrected_value": ["white mask"]}
    commit_headers = api.calls[2][3]
    assert commit_headers["Authorization"] == "Bearer " + "T" * 43
    assert commit_headers["Idempotency-Key"] == "owner-review-local-" + "e" * 32
    assert "T" * 43 not in out.getvalue()


def test_review_without_exact_phrase_never_commits():
    api = FakeApi(_proposal())
    result = cli.review(goal_id=GOAL, base_url="http://127.0.0.1:8765", credential_id="owner-maotai-1",
                        keychain=_keychain_with_token(), http=api,
                        ask=_answers("u", "n", "yes"), out=io.StringIO())
    assert result != 0 and all(not u.endswith("/commit") for _, u, _, _ in api.calls)


def test_needs_human_preview_stops_before_commit():
    api = FakeApi(_proposal(), outcome="NEEDS_HUMAN")
    result = cli.review(goal_id=GOAL, base_url="http://127.0.0.1:8765", credential_id="owner-maotai-1",
                        keychain=_keychain_with_token(), http=api,
                        ask=_answers("u", "n"), out=io.StringIO())
    assert result != 0 and len(api.calls) == 2


def test_dynamic_motion_requires_explicit_opt_in_with_exact_digest():
    motion = {"motion_digest": "f" * 64, "motion": {"events": ["approach", "eat"]}, "shots": []}
    api = FakeApi(_proposal(dynamic_motion_proposal=motion))
    cli.review(goal_id=GOAL, base_url="http://127.0.0.1:8765", credential_id="owner-maotai-1",
               keychain=_keychain_with_token(), http=api,
               ask=_answers("u", "y", "确认提交"), out=io.StringIO())
    body = api.calls[1][2]
    assert body["story_policy_opt_in"] == "dynamic-pet-feeding-v1.0.0"
    assert body["confirmed_motion_digest"] == "f" * 64


@pytest.mark.parametrize("url", ["http://192.168.68.50:8765", "https://127.0.0.1:8765",
                                 "http://localhost.example:8765", "http://127.0.0.1:8765/../x"])
def test_review_refuses_non_loopback_or_unexpected_base_url(url):
    with pytest.raises(SystemExit):
        cli.review(goal_id=GOAL, base_url=url, credential_id="owner-maotai-1",
                   keychain=_keychain_with_token(), http=FakeApi(_proposal()),
                   ask=_answers(), out=io.StringIO())


def test_missing_keychain_secret_fails_closed_without_network():
    api = FakeApi(_proposal())
    with pytest.raises(SystemExit):
        cli.review(goal_id=GOAL, base_url="http://127.0.0.1:8765", credential_id="owner-maotai-1",
                   keychain=FakeKeychain(), http=api, ask=_answers(), out=io.StringIO())
    assert api.calls == []


def test_required_field_paths_match_core():
    from picotoopet_core.autonomous import owner_structured_review as core

    assert tuple(cli.REQUIRED_FIELD_PATHS) == core._REQUIRED_FIELD_PATHS
    assert json.dumps(cli.DYNAMIC_PET_POLICY) == json.dumps(
        __import__("picotoopet_core.creative.dynamic_pet_story", fromlist=["x"]).DYNAMIC_PET_POLICY)
