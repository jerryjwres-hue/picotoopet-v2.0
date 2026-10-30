# Issue 180 — Windows visual observation integration STOP

Status: **BLOCKED / UNVERIFIED**. Frozen source:
`ddc2b3344e96ac52a1370683612dfe5634a615a2`.
Branch: `feature/p0q2-win-auto-visual-review-observation-20261030`.
Contract: <https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/180>.

No reviewer, disconnected observation service, background executor, UI action or
new QA authority is implemented by this note. No actual media or model was accessed.

## Why the STOP condition applies

The issue explicitly says:

> If one existing read-only consumer needs an edit, request narrow scope explicitly before changing it.

It also requires stopping when the existing projection cannot safely provide all
three immutable WebMs and exact Core identities without production-path changes.
The authorized new `Services/QualityObservation/**` files cannot become a visible
WPF action by themselves. No existing Desktop call site references `ReviewRunner`,
`ReviewOptions` or the visual-review tool, and no observation-plugin registration
point was found. A module initializer, reflection hook or interception of an
existing command would evade the ownership boundary; none is added.

| Existing consumer / contract | Frozen-source finding | Consequence |
| --- | --- | --- |
| `ViewModels/ResultsPageViewModel.cs` | Generic terminal task/result metadata; extra safe preview is restricted to `system.diagnostic_snapshot`. | Not an approved Production Job / three-WebM preview route. Do not broaden generic result browsing. |
| `ViewModels/ProductionPanelViewModel.cs` and `Views/ProductionPanel.xaml(.cs)` | Exact selected Production Job ID is available; actions are create, refresh, preflight, start and cancel. No visual-review context/action. | Best candidate for one explicitly approved read-only hook, but all three existing consumer files are outside current edit permission. |
| `Services/GoalFinalVideoCoordinator.cs` | `Observe` can start background final-video assembly; the public snapshot contains readiness/Job ID, not three source WebMs. | Calling it to obtain review inputs would trigger composition, not passive evidence discovery. |
| C011 delivery projection/receipt | Concerns approved final MP4 delivery and technical QA authority. | Do not attach an advisory WebM reviewer to acceptance, opening, receipt writing or rerender paths. |

## Existing facts are useful; their UI projection is missing

This is **not** a claim that Core lacks provenance. Existing authenticated
`ControlCenterSession.GetProductionJobAsync`, `GetProductionPlanAsync` and
`GetProductionPackageAsync` are already read-only entrypoints. The plan contains
ordered task/shot identities; the package manifest's `outputs` retain
`production_task_id`, `shot_id`, exact `output_relpath`, `output_sha256`,
`output_bytes`, MIME, dimensions, frame count and fps. Core creates the completed
package only after every durable task succeeds. No Claim or new Core API is needed
to read that package. No such network calls were made during this investigation.

A future projection must bind exact Job/Plan/Package digests and join precisely
three unique outputs to the frozen plan's task/shot IDs and order. A final MP4,
`production_ready` label, filename pattern or three files found on disk is not a
substitute. The absolute approved local output root and actual file-read permission
are also required; do not treat a guessed fallback root as proof. Missing package,
identity, root, files, matching bytes/hash or stable pins means UNVERIFIED, with no
filesystem search to invent replacements.

## One narrow hook proposed for a separately authorized continuation

Authorize **one consumer: ProductionPanel's selected completed Production Job**.
The precise existing-file scope needed for a normal WPF action is:

- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ProductionPanelViewModel.cs`:
  expose a separate read-only observation command/state for the selected exact ID;
  do not call `_execution`, preflight, start, claim, cancel or compositor actions.
- `windows/desktop/src/PicotooPet.Desktop/Views/ProductionPanel.xaml`:
  one clearly advisory “生成视觉证据（CPU，只读）” action and evidence/status display.
- `windows/desktop/src/PicotooPet.Desktop/Views/ProductionPanel.xaml.cs`:
  forward only that explicit click; selection/session changes invalidate old work.

Everything else should remain in the already authorized new observation files and
focused tests, with only essential reuse/packaging of the existing tool. These
three existing files are **a proposal, not modified files or assumed permission**.
Tool availability/deployment must be explicit; no SDK build on an operator PC,
runtime download, second application or daily CLI surface is an acceptable UI
integration. No official builder change is proposed under this issue.

The adapter should reuse `tools/p0_visual_review` for immutable input validation,
FFprobe, nine frames/timecodes/hashes, CPU contact sheet and optional LAN model
protocol. It must revalidate tool report identities/frame associations and source
hashes before display. Write separate non-authoritative evidence, never a C011
receipt or Core terminal state. Normalize legacy `ADVISORY_REVIEW` to UI `REVIEW`;
retain `REJECT_SUSPECT` and `UNVERIFIED`. Empty flags or model confidence cannot
produce human ACCEPT, approval, rerender or GPU admission.

Focus labels remain advisory: identity/clothing drift, floating/support problems,
product geometry, cross-shot scene continuity and story causality. The existing
schema's `other` concern can carry scene-continuity observations; this is not a new
classifier. Uncertain, malformed, adversarial or misassociated model results stay
REVIEW/UNVERIFIED. A static nine-frame sheet cannot prove motion or causal story.

## Real-media operator step and unverified quality claims

**Proposed future single operator action, unavailable in today's UI:** after the
hook is approved, built and delivered, select the exact completed three-shot Job,
invoke its read-only evidence action and approve reading the displayed exact
source files/hashes. Leave VLM transfer disabled. This is not an instruction to
operate a user device now. The existing standalone CLI is not presented as the
completed Windows integration.

Job `64695948-fb1a-4793-815f-3f6ad4d4d536` remains human **VISUAL_REJECT**.
Its real original WebM paths/hashes/bytes and read-only access permission were not
provided or obtained; no new film or quality verdict is invented. GPU generation,
real visual defect detection, temporal/story accuracy, human-labeled calibration
and first-pass usable-yield measurements all remain UNVERIFIED/unavailable.
Synthetic parser fixtures cannot establish any of these outcomes.

Optional VLM requires separate explicit frame-transfer consent to a validated
private-LAN endpoint and an already available model. Installed, persistently
loaded, completed inference and perceptual accuracy are distinct states; unknown
states must not be inferred as success. Existing tool inference uses three middle
frames, not all nine frames or full video. No model inventory query, inference,
model download, GPU start or LAN transfer occurred here.

## Verification and CI boundary

Only this allowed documentation file changes. `git diff --check` and the existing
portable QualityObservation smoke harness can verify formatting and baseline
policy behavior; neither proves WPF integration or real-film quality. Existing
native workflow `p0-q2-visual-review-native.yml` is reusable for synthetic CPU
evidence. Its push filter does not include this branch and its PR filter does not
include docs-only changes; manual dispatch on the exact branch is required for a
new native baseline run. No unauthorized workflow edit or unused test class is
added just to obtain a green badge. If GitHub dispatch is unavailable, native
verification remains UNVERIFIED and no prior Run ID may be substituted.

Production I2V Claim/Lease, Comfy POST, Worker scheduler, C011, composer, Creative,
Maotai, official release and human authority remain unchanged. The STOP is the
integration/ownership boundary, not a passing visual-quality deliverable.
