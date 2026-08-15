# PicotooPet Interactive Pet + Simple Mode UI v1.3 Design

Date: 2026-08-15
Branch: `feature/interactive-pet-v1-2.3.26.1`
Base: `feature/operator-simple-mode-2.3.26.1`

## Goal

Upgrade the current Windows WPF acceptance branch from v1.2 to v1.3 by improving three areas together: the husky's perceived life and continuity, the desktop-pet interaction model, and the visual quality of the Simple Mode shell/pages. The upgrade must remain an isolated presentation/read-only layer and must not restructure Core, Worker, task, approval, queue/outbox, result, schema, provider, or persistence behavior.

Success means the application feels like one cohesive product rather than a normal control panel with an animated illustration attached. The pet should react continuously and naturally, the UI should visually match the supplied PicotooPet reference more closely, and the same green/orange/gray status semantics must remain truthful and consistent across shell, home, and pet surfaces.

## Non-goals and frozen boundaries

The following remain unchanged:

- Core session and connection architecture.
- Worker lifecycle and execution semantics.
- Task creation, cancellation, status, queue, outbox, result, and retry semantics.
- Approval and review authority.
- Schema and contract versions.
- Provider selection and paid inference behavior.
- Existing local-first and safety constraints.
- The exact five Simple Mode navigation labels: `首页 / 待我审核 / 进行中 / 已完成 / 高级`.

The pet, behavior engine, floating window, decorative scenes, and UI telemetry may only consume already-available read-only facts. They must not create a second durable state source for business truth.

## Chosen approach

Use one integrated v1.3 presentation upgrade rather than separate UI-only or pet-only changes.

The existing `AssistantPetPresentation` remains the single fact-derived base state. A layered pet runtime is added above it:

`System Base State -> Emotion -> Micro Action -> Interaction Override -> Transition`

The visual layer continues to be native WPF. No Electron, WebView, browser runtime, remote animation service, or second executable is introduced.

## Pet behavior architecture

### 1. Base State

`AssistantPetPresentation.Mode` remains authoritative for the real operating condition:

- Resting
- Working
- Waiting
- Offline
- Error

The base state may never be overwritten by a temporary visual reaction.

### 2. Emotion Layer

The v1.2 emotion layer is retained and expanded only where needed for natural behavior. The initial v1.3 set is:

- Calm
- Focused
- Happy
- Curious
- Sleepy
- Concerned
- Playful
- Startled

Emotion changes affect brows, eyes, pupils, ears, mouth, tongue, blush, head pose, and subtle body energy. They do not alter task or system state.

### 3. Micro Actions

The pet gains low-frequency actions that can occur while the base state remains unchanged. Required v1.3 actions:

- LookAround
- Stretch
- Yawn
- LickNose
- LickPaw
- ScratchEar
- CuriousTilt
- HappyBounce
- FocusGlance
- ScreenCheck
- TinySneeze
- SettleDown

Actions use cooldowns, weighted selection, state-specific eligibility, and recent-history suppression. At least the last two completed actions should be excluded from immediate reselection when alternatives exist.

### 4. Behavior Sequences

v1.3 adds short multi-step sequences so the character is not perceived as firing isolated animations. Examples:

- Resting: `LookAround -> CuriousTilt -> Blink -> SettleDown`
- Working: `Typing -> ScreenCheck -> FocusGlance -> Typing`
- Waiting: `LookAtUser -> CuriousTilt -> EarTwitch -> SettleDown`
- User hover: `TrackPointer -> Blink -> TailResponse`
- Head pat: `InteractionOverride -> Happy -> EarRelax -> ReturnToBase`

A sequence is presentation-only and must always have a bounded duration and deterministic return to the current base state.

### 5. Interaction Override

Direct user interaction takes priority over random behavior. Hit regions remain visual-only and are split into at least:

- Head / face
- Ear area
- Paw area
- Body

Expected reactions:

- Head/face click: head pat response.
- Ear click: ear twitch / playful complaint.
- Paw click: high-five / paw wave.
- Body click: happy body bounce.
- Double click: short celebration.
- Drag: bounded character/window movement depending on embedded/floating mode.

Random micro-actions must not interrupt active pointer capture or drag operations.

### 6. Transition Layer

Transitions smooth changes between real states and temporary actions. Required behavior:

- Working <-> Resting uses a short settle/attention transition instead of an abrupt pose replacement.
- Waiting shows a short attention cue before entering the waiting idle loop.
- Offline lowers motion frequency and settles into sleep rather than instantly collapsing.
- Recovery from Offline/Error returns through a wake/recover transition before the normal base loop.

Transitions must remain short and non-blocking and must not delay the display of the truthful status lamp or text.

## Desktop pet v1.3

The existing same-process `FloatingPetWindow` remains the only floating mode.

Retain:

- Transparent frameless window.
- Same `ShellViewModel.PetPresentation` binding.
- Drag handle.
- Topmost toggle.
- Return-to-sidebar action.
- 100% / 115% / 130% scale presets.
- Screen-edge snapping.

Add:

- Better edge-snap hysteresis so minor pointer jitter does not repeatedly snap/unsnap.
- Position clamping that remains correct across the Windows virtual desktop.
- A compact context/tool surface that appears only on explicit hover/click and otherwise stays visually quiet.
- A lock-position toggle so accidental drags can be prevented.
- Animation suspension when the window is hidden/minimized/not visible.

No persistent business state is added. If window position or visual preferences are persisted later, they must live in UI preferences only and must not share storage with business task state.

## Simple Mode UI v1.3

### Shell

- Keep the dark blue left rail but refine gradient, spacing, borders, and depth.
- Make the brand area more compact and intentional.
- Preserve the five frozen navigation labels.
- Improve selected/hover navigation treatment without changing command routing.
- Reduce visual weight in the top status area; use a cleaner status capsule system.
- Keep green/orange/gray lamp semantics identical to `PetPresentation.Indicator`.
- Improve header spacing for 125% and 150% DPI.

### Assistant panel

- Make the pet stage the dominant visual element inside the left rail.
- Reduce emoji-like decorative elements where native vector/WPF shapes can communicate the same state.
- Keep readable status text so color is not the only signal.
- Preserve the float-to-desktop affordance but visually demote it until hover/focus.

### Home page

- Refine the hero into one cohesive workspace banner with stronger composition between task CTA, system context, and mascot.
- Keep all counts and telemetry truthful; no placeholder numbers.
- Make the status summary strip visually lighter and easier to scan.
- Normalize card radius, border, shadow/depth, spacing, and headings across task overview, recent tasks, system status, resources, and work components.
- Improve empty-state composition without manufacturing fake tasks.

### Review and task-list pages

- Apply the same card hierarchy, typography, spacing, and status-chip system as Home.
- Preserve all existing view-model bindings and write authority.
- No new approval or task commands are introduced by the visual refresh.

### Responsive/DPI behavior

The target acceptance set is:

- 100% DPI at 1920x1080.
- 125% DPI at common laptop resolutions.
- 150% DPI at common high-DPI laptop resolutions.
- Minimum supported shell size without clipped primary navigation or broken pet controls.

Layout should prefer responsive width allocation and scroll containment over fixed pixel assumptions where practical.

## Data flow

1. Existing Core/Worker/task facts update the existing session snapshot.
2. `AssistantPetPresentation.FromSnapshot(...)` derives the truthful base pet mode and green/orange/gray indicator.
3. `ShellViewModel.PetPresentation` exposes the projection to WPF.
4. `AssistantPetPanel` passes the current base mode and interaction availability to the behavior runtime.
5. The behavior runtime returns presentation-only frames/sequences.
6. WPF named visual parts apply the frame while preserving the base state.
7. On completion/interruption, the renderer returns to the latest current base state, not the state that existed when the temporary action began.

This last rule is required so a task/state change during a pet reaction cannot leave the pet visually stuck in a stale state.

## Failure isolation

The pet/UI upgrade must fail closed as a presentation feature:

- Behavior selection failure: fall back to the current base pose.
- Animation exception: stop the affected animation and retain readable status text/lamp.
- Missing optional visual resource: use vector/native fallback and keep the rest of the shell functional.
- Floating window failure: keep the sidebar pet operational.
- Resource telemetry failure: continue to show `—` instead of fabricated values.
- Dispatcher/timer shutdown: all continuous timers and animations stop on unload/visibility loss.

No presentation exception may be allowed to alter Core/Worker/task state.

## Performance constraints

- Continuous timers must stop while visuals are not visible.
- Random behavior should use low-frequency scheduling rather than frame-rate polling.
- Pointer tracking should only run while the pointer is inside the relevant pet surface.
- Repeating animations should use WPF transforms/opacity rather than layout-heavy property changes where possible.
- The v1.3 pet must not introduce remote asset loading or runtime inference.

## Test strategy

### Contract/smoke tests

Add a v1.3 smoke contract covering:

- Presence of the behavior sequence scheduler/runtime.
- Required v1.3 emotion and micro-action names.
- Interaction-priority and return-to-current-base-state contract.
- Floating-pet lock-position and snap helpers.
- Shell/Home v1.3 named visual surfaces required for regression detection.
- Continued absence of business write methods on pet behavior/rendering types.

### Existing gates

All existing gates remain mandatory:

- Contract/security tests.
- Legacy Task Center regression reproduction.
- WPF smoke tests.
- Warnings-as-errors build.
- Published executable self-test.
- Native Windows delivery invariants.
- Installer project-goal validation.
- Install / upgrade / recovery / rollback lifecycle.

### Manual acceptance focus

The human acceptance pass should focus on:

- Whether the pet feels continuous rather than random/robotic over several minutes.
- Whether direct interactions visibly take priority and then return naturally to the correct live system state.
- Whether the overall UI now matches the supplied PicotooPet visual direction more closely.
- Whether green/orange/gray status recognition remains immediate.
- Whether 125%/150% DPI and smaller windows remain usable.
- Whether floating-pet placement, snapping, scaling, lock-position, and return-to-sidebar interactions feel stable.

## Delivery

Implementation stays on the existing Draft PR branch until all automated gates are green and real-machine visual acceptance is complete. The PR must remain unmerged during the acceptance cycle. The final deliverable is a new Windows Prebuilt acceptance artifact and a user-facing installer ZIP for v1.3.
