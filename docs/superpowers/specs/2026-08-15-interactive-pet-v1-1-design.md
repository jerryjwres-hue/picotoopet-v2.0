# Interactive Pet v1.1 Design

## Goal

Complete the Windows acceptance candidate as one cohesive product pass: richer native pet behavior, an optional floating desktop-pet surface, truthful local resource monitoring, consistent green/orange/gray health semantics, and additional UI polish without changing the Core / Worker / task / approval authority model.

## Non-negotiable architecture boundary

- The formal process remains the existing native WPF `Picotoo Pet AI.exe`.
- No second executable, Electron shell, WebView, browser runtime, Provider call, remote asset request, paid inference, or new durable state source.
- Pet and resource-monitor features are presentation/read-only features.
- Existing Core, Worker, task, approval, queue, outbox, result, and schema semantics remain authoritative and unchanged.
- The five Simple Mode entries remain exactly `首页 / 待我审核 / 进行中 / 已完成 / 高级`.

## Desktop-pet behavior

`AssistantPetPanel` remains the reusable articulated WPF character renderer. The character is built from independent visual parts and receives the existing `AssistantPetPresentation` projection.

v1.1 adds:

- richer idle micro-actions with bounded randomized timing;
- separate head/ear/paw/tail/eye reactions rather than whole-image motion;
- working typing cadence and occasional screen attention;
- resting bath bubbles / duck motion;
- offline sleeping breath and floating Z motion;
- presentation-only particles for friendly reactions;
- animation suspension while the visual is not visible.

## Optional floating mode

A single `FloatingPetWindow` is created by the existing Shell only when the user requests it.

- transparent, frameless, top-most WPF window;
- not shown in the taskbar;
- uses the same `AssistantPetPanel` and the same `ShellViewModel.PetPresentation` instance;
- contains a small explicit drag handle so pointer interactions on the character still work;
- can be returned/closed without affecting the main Shell or any operational state;
- owned and disposed by the existing Shell lifecycle.

`AssistantPetPanel.IsFloatingMode` hides card chrome and keeps only the articulated character stage plus subtle status lamp, so floating mode feels like a desktop pet rather than a second application panel.

## Truthful Windows resource monitoring

The current placeholder resource card is replaced with local read-only measurements:

- CPU: Win32 `GetSystemTimes` deltas;
- memory: Win32 `GlobalMemoryStatusEx`;
- disk: managed `DriveInfo` for the Windows system drive.

No PerformanceCounter package or third-party dependency is added. Sampling is local, bounded, and stops while the home page is unloaded. Sampling failure displays `—` instead of fabricated percentages.

## Status-color semantics

One product-wide vocabulary is preserved:

- Green: online / healthy / normal work / normal rest.
- Orange: user attention or connection/authentication fault.
- Gray: offline / worker unavailable / unavailable measurement.

Color is never the sole carrier of meaning; text remains visible.

## Stability requirements

- Animation timers stop when controls are unloaded or invisible.
- Floating window cannot issue task or approval commands.
- Resource sampling exceptions are isolated from navigation and task execution.
- Missing/failed UI telemetry degrades to placeholders.
- Existing navigation and fatal-error boundaries remain intact.
- Windows contract/security tests, WPF smoke, warnings-as-errors build, self-test, installer validation, and install/upgrade/recovery/rollback lifecycle must all pass before the combined acceptance package is presented.
