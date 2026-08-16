# Windows UI Interaction Polish Plan — 2.3.27.1

## Goal

Make the native WPF Control Center feel responsive, trustworthy, and coherent. Any surface that looks interactive must have a real action; unavailable actions must explain why; task/result surfaces must open useful detail; async actions must show progress and safe failure feedback. Preserve the separate Maotai pet integration boundary and do not invent pet internals here.

## Product invariants

- Keep the formal native WPF `Picotoo Pet AI.exe`; no helper/web UI.
- Mac Core remains source of truth for tasks/results/visibility.
- Research remains read/search only.
- Safe delete remains reversible: active tasks cancel then hide; completed tasks hide; deleted tasks can be restored.
- Do not change Mac Core/Worker/Gateway contracts in this UI-only pass.
- Do not implement or replace the separately developed Maotai interaction component. Preserve `AssistantPetPanel` as the integration slot.

## Interaction system

1. **No dead affordances** — button/card/link visuals must map to `Command`/`Click`; decorative surfaces must not use hand cursors or button styling.
2. **Single-source navigation** — simple-mode sidebar is generated from `ShellViewModel.NavigationItems`; no XAML five-item list plus runtime sixth-item injection.
3. **Task-first navigation** — recent tasks, task lists, Task Center rows, and Results rows open one shared `TaskDetailWindow` path when a task can be resolved.
4. **Result-first detail** — completed/Research results are readable from the normal task detail path; diagnostics retain their specialized presentation where useful.
5. **Async feedback** — disable duplicate actions while busy; show action-progress text; preserve safe error messages and retry/recovery paths.
6. **Safe deletion UX** — single and batch delete/restore always report outcome; deleted items live in `已删除` and remain viewable before restore.
7. **Readable typography** — normal UI text >= 12 DIP, body 14 DIP, secondary 13 DIP, buttons/nav 14–15 DIP, section headings 18 DIP, page headings 24–26 DIP; PerMonitorV2 stays enabled.
8. **Accessible interaction** — visible keyboard focus, >= 38 DIP normal controls, tooltips/reasons for unavailable actions, meaningful `AutomationProperties.Name` on non-text actions.
9. **Useful states** — loading, empty, success and error states say what happened and what the user can do next.

## Implementation slices

### Slice A — interaction contract + navigation
- Add a release contract that audits normal WPF XAML for dead button affordances and undersized explicit fonts.
- Replace hard-coded simple sidebar buttons/runtime insertion with one ItemsControl bound to `NavigationItems`.
- Keep selected/disabled styling and availability reason.

### Slice B — task/result click-through
- Make Home recent-task cards real buttons.
- Make Task Center rows open shared task detail without stealing selection/action controls.
- Make Results support generic/Research result detail instead of diagnostics-only preview.

### Slice C — visual/feedback system
- Centralize button focus/hover/pressed/disabled states and hit targets in `App.xaml`.
- Replace remaining normal-shell 8–11 DIP text with the approved scale.
- Add busy/progress affordances and outcome text for destructive/restorative task actions.

### Slice D — full-page dead-affordance audit
Audit every normal WPF page/panel under `Views/Pages` and `Views`:
- Approval, Automation, Business Automation, Cloud Development panels, Diagnostics, Health, Projects, Settings, New Task, Results, Task Center, simple pages.
- Every visual action is wired, explicitly disabled with reason, or converted to non-interactive presentation.

### Slice E — native release verification
- `dotnet restore/test` release solution.
- protected Task Center binding regression.
- Research/release governance contracts.
- published self-contained EXE self-test.
- goal-integrity stamp/verify.
- install -> upgrade -> recovery -> rollback lifecycle.

## Acceptance

A user can traverse every visible navigation entry, open task/result detail from all task-oriented surfaces, safely delete/restore singly or in batches, understand unavailable actions, use keyboard focus, and never encounter a control that looks clickable but has no defined behavior. UI text remains clear at common Windows DPI scales. The Maotai slot remains untouched and ready for the separately developed component.