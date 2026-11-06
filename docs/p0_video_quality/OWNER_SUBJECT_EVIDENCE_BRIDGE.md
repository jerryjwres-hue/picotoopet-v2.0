# P0 — PET_ONLY owner-source evidence bridge (review candidate)

## Source of the STOP

The installed pet-only Video Bible v1.0.1 already accepts the correct 3×4-second story.
The fifth local model attempt returned schema-valid `needs_human=true` because all six
synthesis findings were `unverified_inference` and lacked owner-grounded identity,
visible-scene and action-intent evidence. Do not retry or alter the terminal Job.

## Reused components — no second source of truth

- Existing Mac Core `canonical_evidence` ledger (schema 020) stores exact subject keys.
- Existing authenticated `/api/v1/autonomous/owner-subject-evidence/preview` returns
  only a canonical packet digest; it writes nothing.
- `.../commit` requires `owner_confirmed=true` plus the same exact digest. The
  server stores owner statements as `origin_kind=manual`, with immutable packet
  lineage and individual evidence IDs. Invalid/different digests fail closed.
- The snapshot's photo SHA-256 is **owner-supplied metadata**, not proof the server
  read or verified photo bytes. Owner statements use trust D and intended actions E;
  no source is mislabeled as product or independent observation.
- A **new** authenticated `video.creative` Goal may opt in to
  `owner_subject_key="pet:<id>"`. Goal Core persists this scope in immutable
  constraints, freezes it into the Discovery task, and rejects it for commercial
  product/video modes or when the objective is not explicitly `pet-only story`.
- The existing Mac Worker reads precisely the selected subject's canonical manual
  evidence. Discovery rejects missing identity, visible-scene or creative-intent
  facts before spending another Creative call.
- Existing Synthesis and Creative consume real Discovery/ResultStore hashes.
  Synthesized text remains `unverified_inference`; individual reviewed owner
  statements become `owner_attested` or `creative_intent` with their *own*
  evidence IDs and digests, even when the model omits some owner evidence IDs from
  its analysis. The direct Discovery identity remains bound to the original
  ResultStore hash; no additional untrusted inference is promoted.

## Human review and privacy

Do not submit private photo data, real user facts, credentials, or location coordinates
to GitHub. Prepare an owner-reviewable local packet on the Mac with a stable pet key,
the **claimed** SHA-256 of the original private photo, and three separate claim types:

1. `visible_identity`: owner-confirmed species, coat, facial marks and accessories.
2. `visible_scene`: owner-confirmed **visible** environment/support from the first photo.
3. `creative_intent`: a proposed blink or gentle motion, **not** observed footage.

The owner must review exactly those statements and approve the preview digest before
the API commit. An authenticated payload asserting `owner_confirmed` is only an owner
attestation; it is **not** a production/rights/GPU approval. The actual photo bytes
and production rights remain under the existing independent `production/references`
human acceptance and Windows managed snapshot flow.

## Gate sequence

1. Native Mac Core + Worker CI, security/API tests and product-mode regressions PASS.
2. User separately authorizes a bounded Core/Worker candidate deployment.
3. Owner privately reviews and explicitly confirms exact subject claim packet.
4. Verify canonical evidence IDs and read-only Goal source preview; no fake product.
5. Only after new authorization create one immutable local `video.creative` Goal with
   `owner_subject_key`, 3×4 sec and affirmative `pet-only story`.
6. A true PASS Creative Package is still required before reference approval,
   frozen Production Plan, signed Witness, GPU HOLD review and the single-shot I2V.

If a source, signature/approval, digest, subject, scope or model quality gate is missing:
**STOP.** Never auto-set `needs_human=false` or generate a test Goal to mask failure.

## Test scope

Synthetic-only data; deterministic tests cover preview/no-write, idempotent commit,
digest rejection, source type separation, private subject isolation, product-mode
rejection, Discovery fail-closed and Creative provenance without any Ollama/GPU use.
