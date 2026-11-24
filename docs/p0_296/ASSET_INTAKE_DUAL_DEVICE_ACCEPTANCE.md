# P0 asset intake: bounded Mac/Windows candidate acceptance

Scope: existing assets only, no rendering. Stacked base PR #351 at
`88521c89a69da931bb5fe896bdb4b945ee76b6dc`. Its dependencies #349 and #350
remain Draft. Do not merge or replace the production install automatically.
The portable Windows preview is unsigned and explicitly NOT a formal release
or installer. Native Mac Core package is a development candidate, not production approval.

## 1. CI / candidate identity

- One exact candidate HEAD for the Mac Core arm64 package and Windows x64 ZIP.
  Verify that both workflow checkouts identify that full commit SHA.
- Require successful native workflow runs, downloaded archive SHA-256 against
  the trusted CI receipts, and the existing package manifest validators.
  The outer GitHub artifact digest and inner package digest are different.
- Mac Worker is unchanged in this patch; do not install, resume or upgrade it
  merely to test asset intake. Do not start the Supervisor.
- A CI artifact with a diagnostic/failure label is not an install candidate.
  No local deployment is authorized by a passing CI alone.

## 2. Mac Claude — preflight, then separately authorized Core-only evaluation

1. Read current release version, active Core health, DB schema and existing
   task/approval/production queue counts without printing the bearer token.
2. Confirm existing database backup and rollback path, native arm64,
   Python 3.12, and that Worker/Supervisor cannot claim existing Ready work.
   STOP if active work or a safe rollback/backup cannot be confirmed.
3. Only after explicit operator permission for internal evaluation, use the
   package's existing INSTALL_MAC_CORE_SLICE_B.command and VERIFY command
   according to its README. Keep loopback binding, original token and schema 24.
   Never run Worker/Supervisor to verify this test.
4. Verify authenticated OpenAPI shows these canonical routes:
   - POST /api/v1/studio/assets/import
   - POST /api/v1/studio/assets/windows-evidence
   - GET /api/v1/studio/assets/by-sha256
   - POST /api/v1/studio/assets/{artifact_id}/owner-approval-request
   - GET /api/v1/studio/assets/{artifact_id}/production-eligibility
   - POST /api/v1/studio/storypacks/preview
5. Do not import private files from a public guest share or use an untrusted
   endpoint. Stop on failed package verification or unexpected task execution.

Report exact source/inner SHA, Core-only activation status, DB schema and
counts, API route availability, and rollback availability; never send credentials.

## 3. Windows Claude — after Core and secure connection verified

1. Use the exact portable candidate only with explicit internal-evaluation
   permission, in a new folder. Do not overwrite the production executable.
   Keep persistent GPU HOLD and use the existing secure SSH loopback tunnel
   (approved key/known_hosts) or existing trusted HTTPS connection.
   Do not start any Worker, ComfyUI or LTX process for this acceptance.
2. Use the actual existing project in Film Studio and load a separate draft
   copied from the original 11-21 StoryPack. Do not overwrite its source
   bytes; retain the existing output_profile. No implicit landscape/portrait conversion.
3. Select the existing C8B character master, B1 scene master and identity lock
   v2 through the three existing file pickers. Match the complete hashes
   from the local read-only inventory. Confirm each copy to the paired Core.
   Reuse prior registered IDs only if exact project, type, digest and integrity match.
4. Select the already trained Maotai LoRA v2 in the new SHA-only registration
   picker. The app locally hashes the exact 46,223,616-byte file. Archive-only
   v1 is not a substitute. No LoRA bytes or Windows path are sent.
5. A separate confirmation may request Owner review. Do not click approve
   on behalf of the Owner; an existing valid approval may be reported but
   must not be invented. The Core's LoRA row is a Windows digest claim,
   not independently Core-verified file bytes or model compatibility.
6. Repeat the read-only StoryPack preview using the returned artifact IDs.
   Verify exact actions, dependencies, state transitions and source profile.
   The production bridge remains non-executable: trusted per-shot frames,
   package authority, compatible renderer, and formal review are missing.
   No Goal creation, Worker lease, production attempt or GPU submission.

Report only artifact IDs, full digests, integrity/provenance, approval
request IDs/status, StoryPack draft digest/profile, blockers, and GPU_POST=0.
Do not regenerate the failed Qwen images, C8B, B1, LoRA or training data.

## 4. Next implementation scope (not executed here)

Reuse the reported existing `run_flux_board.py` and FLUX.2 Klein 4B +
Maotai v2 LoRA (strength 0.9, trigger mtai_dog). The exact local script/graph
and model bytes still require authenticated local validation; do not build a
speculative replacement. LTX Desktop Remote `ltx-2.5-fast` I2V is a reported
historically successful route, but the production adapter, local execution
mode, output profile and per-shot provenance still require verification.
Do not substitute the failed direct LTX CLI route.

Keep the original horizontal StoryPack unchanged. A portrait derivative
must be a separate version, with explicit operator selection and verified
geometry. No new GPU work until a reviewed per-shot input path exists.
