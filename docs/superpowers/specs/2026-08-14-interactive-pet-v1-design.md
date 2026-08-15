# Interactive Pet v1 Design

## Goal

Turn the approved husky in Simple Mode into a native WPF interactive pet that lives inside the existing Picotoo Pet AI window, reflects real Mac Core / Worker / task facts, and reacts locally to pointer input without becoming a second state source.

## Product surface

- Keep the formal Windows application as the existing native WPF `Picotoo Pet AI.exe`.
- Place the pet in the existing left sidebar below the five Simple Mode navigation entries so it remains visible while the user changes pages.
- Do not add Electron, WebView, browser UI, helper executable, second tray application, or a new control plane.
- The pet is presentation-only. It never creates, completes, cancels, approves, rejects, leases, or mutates a task.

## State model

`AssistantPetPresentation.FromSnapshot(ControlCenterSessionSnapshot)` derives one base visual state from existing facts only.

Priority is deterministic:

1. `Error` when the Core connection is `AuthenticationFailed` or `Faulted`.
2. `Offline` when Core is not online or Worker is unavailable.
3. `Working` when at least one task is non-terminal and not waiting for human approval.
4. `Waiting` when at least one task is waiting for human approval and nothing is actively executing.
5. `Resting` when Core and Worker are healthy and no task requires work or review.

`Resting` is a friendly visual name for the existing online/idle fact; it is not a persisted operational state.

Interaction animations are temporary presentation overlays. When an interaction ends, the renderer returns to the current fact-derived base state. Pointer interaction can never overwrite or persist a system state.

## Visual assets

Store transparent PNG resources under:

`windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Husky/V1/`

Initial assets:

- `idle.png` — friendly paw-up pose used for waiting / interaction response.
- `working.png` — headphones + laptop + drink.
- `resting.png` — bubble bath + rubber duck.
- `offline.png` — sleeping pose + Z symbols.

All assets are local application resources. There is no runtime network fetch, paid model call, telemetry upload, or generated-content request.

## WPF components

### `AssistantPetPresentation`

Pure deterministic projection that owns the pet mode, visible label, detail text, and asset key. It depends only on `ControlCenterSessionSnapshot`.

### `ShellViewModel`

Owns the current `AssistantPetPresentation` because the pet is global sidebar chrome. Every accepted session snapshot recalculates the projection and raises property changes. No second persistence model is introduced.

### `InteractivePetPanel`

A focused WPF `UserControl` that binds the presentation and renders the corresponding local image. Its code-behind owns presentation-only motion:

- continuous soft breathing / vertical bob;
- pointer-follow head/body tilt within a small bounded angle;
- click bounce and temporary paw-wave response;
- smooth fade when the fact-derived image changes;
- reduced motion when the control is not visible or unloaded.

The component never calls `ControlCenterSession` and has no task command capability.

## Motion behavior

- Resting: slow breathing and gentle bob.
- Working: smaller, quicker bob to suggest typing / attention.
- Waiting: idle image with occasional tilt; pointer click produces a short paw-wave emphasis.
- Offline: very slow breathing only.
- Error: no playful bounce; small bounded shake when the state first appears.

All motion uses WPF transforms and storyboards on the UI thread. The source PNGs remain crisp and transparent.

## Error and safety boundaries

- A missing pet asset must not crash navigation or task operations. The control falls back to a text status while the existing navigation fault boundary remains intact.
- Pet presentation cannot invent terminal task state.
- No new file-system scan, user-file enumeration, provider credential access, logs-body capture, or network request is added.
- No release or installer workflow changes are required for v1 beyond including WPF resource files in the existing executable package.

## Verification

TDD coverage will prove:

- each fact pattern maps to the correct pet mode;
- active work outranks waiting review;
- offline/error mapping follows Core and Worker facts;
- the Simple Mode shell contains the pet control without changing the five frozen navigation entries;
- the WPF control measures and arranges successfully in STA smoke tests;
- the full Windows smoke suite and warnings-as-errors build remain green on GitHub Actions.
