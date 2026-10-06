# C002 — Goal Center Web GPT Return Intake

## Goal

Close the remaining manual-product gap after C001 without rebuilding Creative or Production:

```
Goal Center
  -> verified handoff ZIP + bound prompt
  -> manual Web GPT
  -> user copies Web GPT return
  -> Windows Goal Center submits bounded JSON
  -> existing Mac Core C001 video-return endpoint
  -> existing Creative adoption
  -> existing Production job
  -> Windows shows continuation status
```

## Branch / baseline

Work only on `feature/goal-video-return-intake-ui`.

This branch starts from C001 head `ffa711cf82615a137f1b29a07aab560c176cddce`.
Before coding, merge the current tip of
`feature/autonomous-intelligence-e2e-goal-center-2.3.27.1`
into this branch. Do not rebase the shared C001 branch and do not merge any PR to the base branch.

Preserve all C001 behavior.

## Existing backend — MUST reuse

Do not create new return/adoption/production domains.

Existing endpoints:
- `POST /api/v1/autonomous/goals/{goal_id}/handoff/video-return`
- `GET /api/v1/autonomous/goals/{goal_id}/handoff/video-return`

Existing response:
- `GoalVideoContinuationRecord`
  - goal_id
  - handoff_sha256
  - return_sha256
  - creative_job_id
  - creative_package_id
  - creative_package_digest
  - creative_status
  - production_job_id
  - production_status

Existing Core validation remains authoritative:
- strict `GoalVideoReturnV1`, `extra="forbid"`
- goal_id + handoff_sha256 + prompt_version binding
- evidence allowlist
- forbidden-authority gate
- immutable replay semantics
- canonical Creative adoption
- existing ProductionService

## Product UX

In the existing Goal Center handoff area, when `HandoffReady == true`:

1. Keep existing buttons:
   - 复制 GPT 提示词
   - 保存交接 ZIP

2. Add one primary continuation action:
   - `粘贴 GPT 返回`

3. Button behavior:
   - read Windows clipboard text only when clicked
   - do not continuously monitor clipboard
   - never auto-open/login/upload to web GPT
   - parse bounded input locally
   - submit to the current Goal only
   - show a safe success/failure message
   - refresh continuation status immediately

4. Status:
   - before adoption: explain that the Web GPT return has not been submitted
   - after adoption: show Creative status and Production status from Mac Core
   - refresh status with the existing Goal Center refresh cadence
   - 404 from GET means "not submitted yet", not an error banner

No new durable Windows-side lifecycle state.

## Windows return parsing boundary

Windows is NOT allowed to duplicate the full `GoalVideoReturnV1` schema.

Add a small helper that only performs transport/syntax handling:

- max UTF-8 input size: 512 KiB
- accept either:
  - a bare JSON object, or
  - text containing exactly one `PICOTOO_RETURN_JSON` marker followed by the JSON object
- optionally tolerate one surrounding Markdown ```json ... ``` fence
- root must be a JSON object
- reject duplicate marker
- reject oversized input before POST
- reject malformed JSON
- do not add/remove/rename payload fields
- do not rewrite values
- do not validate evidence, binding, model fields, prompts, provider, workflow, renderer, endpoint, path, or command authority
- Core remains the only semantic validator

Do not persist the raw Web GPT response to disk, settings, logs, or telemetry.

## Expected implementation surface

Prefer minimal extension of existing files/classes:

- `windows/desktop/src/PicotooPet.Desktop.Core/Contracts/GoalCenterContracts.cs`
  - add `GoalVideoContinuationRecord`
  - do NOT mirror `GoalVideoReturnV1`

- `windows/desktop/src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs`
  - bounded POST method for video return using parsed `JsonElement`
  - GET continuation status method
  - reuse existing auth, trace, error, response-size boundaries

- `windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Goals.cs`
  - thin wrappers only

- `windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs`
  - continuation projection/state
  - submit method
  - refresh GET status
  - safe status text

- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/GoalCenterPanel.xaml`
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/GoalCenterPanel.xaml.cs`
  - one explicit paste/submit action
  - clipboard read occurs only on click
  - no token handling

A separate parser/helper file is acceptable if it keeps the ViewModel/client small.

## Security / architecture invariants

- Mac Core remains source of truth.
- Windows never creates Workflow/Task/Creative/Production facts directly.
- No provider/model/renderer/workflow/endpoint/path/command controls.
- No credentials in UI/ViewModel.
- No arbitrary local file path authority.
- No automatic browser automation or Web GPT login/upload.
- No duplicate Creative or Production implementation.
- No Business ResultPackage.
- No new database schema/table for this UI.
- Research Gateway remains read-only.
- Do not touch:
  - `deploy/macos/**`
  - `src/picotoopet_core/db/**`
  - Worker install/rollback code
  - Natural Motion / torso asset gate

## Idempotency / replay

The backend already provides deterministic replay behavior.

Windows must:
- allow a user to retry the same return after transient network failure
- not synthesize a different payload
- show Core 409 conflicts as a safe non-retryable return conflict
- after a successful or ambiguous POST, GET status may be used to reconcile

Do not add a second idempotency protocol.

## Error UX

Map errors narrowly:
- malformed/oversized clipboard input -> local safe validation message
- 401/403 -> pairing/auth message
- 404 GET -> no adopted return yet
- 409 POST -> return rejected/conflicted; preserve current Goal/handoff facts
- retryable network failure -> retry message
- unknown -> generic safe message

Never display raw exception bodies or payload content.

## Tests required

At minimum:

1. Parser unit tests
   - bare JSON
   - marker + JSON
   - optional json fence
   - duplicate marker rejected
   - malformed JSON rejected
   - non-object root rejected
   - >512 KiB rejected
   - payload values preserved

2. MacCoreClient tests
   - exact POST path
   - exact GET path
   - auth/trace behavior remains existing behavior
   - POST body is the parsed object, not wrapped in another property
   - bounded response handling
   - 409 surfaces as ApiException

3. ViewModel tests
   - action unavailable without completed video handoff
   - 404 status is treated as not-yet-submitted
   - successful submit stores only continuation projection, not raw GPT text
   - refresh reconstructs status from Core
   - retryable network failure does not invent success

4. Windows behavior/contract tests
   - Goal Center retains existing handoff buttons
   - new paste action is visible only for ready handoff
   - no device token or Web GPT credential handling added to UI

5. Existing regression
   - Windows Control Center CI
   - relevant Core contract tests if shared contracts changed
   - Ruff/shell checks must remain unaffected

## Acceptance criteria

PASS only if a real user flow is possible:

1. Create/complete a video Goal.
2. Save handoff ZIP and copy bound prompt.
3. Send both manually to Web GPT.
4. Copy the Web GPT response.
5. Click `粘贴 GPT 返回` in Windows.
6. Windows submits the exact parsed object to the C001 POST endpoint.
7. Core validates/adopts it and creates/reuses the canonical Production job.
8. Windows shows Creative/Production continuation status from the GET endpoint.
9. Same return retry is idempotent.
10. Conflicting return is rejected without mutating the accepted package/job.

## Stop conditions

Do not merge, tag, release, or bypass any release gate.
Do not touch the known `torso_neutral.png` gate.
If a backend change appears necessary, stop and report the exact missing backend contract before implementing a parallel path.
