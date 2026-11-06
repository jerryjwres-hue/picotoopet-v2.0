"""Bounded, explicitly reviewed owner statements in the existing Core evidence ledger.

Owner testimony is not image verification. A supplied photo SHA is always a *claim*
until original bytes are separately checked by the authorized reference workflow.
No product record, second registry, external upload or GPU authority is created.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence_ledger import (
    CanonicalEvidenceCreate,
    CanonicalEvidenceLedger,
    CanonicalEvidenceRecord,
    EvidenceOrigin,
    EvidenceTrust,
)


class OwnerSubjectClaimKind(StrEnum):
    VISIBLE_IDENTITY = "visible_identity"
    VISIBLE_SCENE = "visible_scene"
    CREATIVE_INTENT = "creative_intent"


class OwnerSubjectClaim(BaseModel):
    """Small owner-authored statement; an intended action is not prior footage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: OwnerSubjectClaimKind
    statement: str = Field(min_length=10, max_length=500)


class OwnerSubjectEvidencePacket(BaseModel):
    """The exact claim sheet to preview, explicitly confirm, and ingest once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_key: str = Field(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$", max_length=68)
    photo_sha256_claim: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: list[OwnerSubjectClaim] = Field(min_length=3, max_length=10)

    @model_validator(mode="after")
    def require_minimum_grounding(self) -> OwnerSubjectEvidencePacket:
        kinds = {claim.kind for claim in self.claims}
        if kinds != set(OwnerSubjectClaimKind):
            raise ValueError("OWNER_SUBJECT_IDENTITY_SCENE_AND_INTENT_REQUIRED")
        if len({(claim.kind, claim.statement) for claim in self.claims}) != len(self.claims):
            raise ValueError("OWNER_SUBJECT_DUPLICATE_CLAIM")
        return self

    def digest(self) -> str:
        document = self.model_dump(mode="json")
        raw = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class OwnerSubjectReview(BaseModel):
    """Two-step confirmation of the exact packet, not an autonomous approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet: OwnerSubjectEvidencePacket
    reviewed_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_confirmed: Literal[True]


class OwnerSubjectEvidenceIntake:
    """Use the *existing* Core evidence ledger with an immutable owner claim scope."""

    def __init__(self, ledger: CanonicalEvidenceLedger) -> None:
        self.ledger = ledger

    @staticmethod
    def preview(packet: OwnerSubjectEvidencePacket) -> dict[str, object]:
        return {
            "packet_digest": packet.digest(),
            "subject_key": packet.subject_key,
            "claim_count": len(packet.claims),
            "photo_bytes_verified": False,
            "owner_confirmation_required": True,
        }

    def ingest(self, review: OwnerSubjectReview) -> list[CanonicalEvidenceRecord]:
        packet = review.packet
        digest = packet.digest()
        if not hmac.compare_digest(digest, review.reviewed_digest):
            raise ValueError("OWNER_SUBJECT_REVIEW_DIGEST_MISMATCH")

        records: list[CanonicalEvidenceRecord] = []
        for index, claim in enumerate(packet.claims, start=1):
            # Each statement is independently citable; the reviewed packet binds all claims.
            # Never turn a proposed creative action into an observed historical fact.
            intent = claim.kind is OwnerSubjectClaimKind.CREATIVE_INTENT
            record = self.ledger.ingest(
                CanonicalEvidenceCreate(
                    subject_key=packet.subject_key,
                    evidence_type=f"pet.owner.{claim.kind.value}",
                    source="owner_attestation",
                    platform="private_mac_core",
                    text_value=claim.statement,
                    value={"claim_kind": claim.kind.value},
                    trust_level=EvidenceTrust.E if intent else EvidenceTrust.D,
                    confidence=0.5 if intent else 0.8,
                    captured_at=datetime.now(UTC),
                    provenance={
                        "owner_reviewed": True,
                        "reviewed_packet_sha256": digest,
                        "photo_sha256_claim": packet.photo_sha256_claim,
                        "photo_bytes_verified": False,
                        "evidence_basis": (
                            "proposed_motion" if intent else "owner_statement"
                        ),
                    },
                    origin_kind=EvidenceOrigin.MANUAL,
                    origin_ref=f"pet-owner:{digest}:claim:{index:02d}",
                )
            )
            records.append(record)
        return records
