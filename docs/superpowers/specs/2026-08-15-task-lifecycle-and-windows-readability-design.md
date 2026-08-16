# Task Lifecycle, Result Detail, and Windows Readability Design

## Scope

This change extends the existing Windows Control Center without creating a parallel UI. It covers two related operator-facing areas:

1. Task lifecycle controls for the simple-mode **进行中**, **已完成**, and new **已删除** views.
2. Whole-application typography and DPI/readability improvements for the existing WPF application.

The Mac Core remains the authoritative task/result store. Windows never hides or deletes task records only in local memory.

## Task lifecycle behavior

### Safe delete

“删除” is a reversible archive operation, not physical deletion.

- For terminal tasks (`Completed`, `Failed`, `Cancelled`), delete transitions the task to `Archived` through Mac Core.
- For active tasks, delete first requests cancellation. The task is archived only after Mac Core reports a terminal state.
- Archived tasks disappear from **进行中** and **已完成** and appear in **已删除**.
- Result objects, attempt history, audit records, and task identifiers remain intact.

### Restore

Restoring an archived task removes it from **已删除** and places it back into the normal visible history.

Because the frozen state machine does not allow `Archived -> Completed/Failed/Cancelled`, restore must not rewrite historical state. Instead, Mac Core stores a separate reversible `hidden/archived` presentation flag for user-managed deletion while preserving the immutable execution state. Existing `Archived` execution-state semantics remain available for system archival and must not be overloaded.

The user-visible safe-delete contract therefore uses a dedicated task-visibility repository/API:

- `DELETE /api/tasks/{task_id}/visibility` (or equivalent fixed action endpoint) marks the task hidden.
- `POST /api/tasks/{task_id}/restore` restores visibility.
- Batch operations accept only explicit task IDs and return per-task outcomes.

No endpoint performs physical deletion.

### Bulk selection

Both **进行中** and **已完成** show a selection checkbox per task and a page-level selection control.

- `全选当前页` selects only currently visible items.
- `删除所选` sends explicit task IDs to Mac Core.
- A destructive confirmation summarizes the number of tasks and whether any active task will be cancelled first.
- Partial failures remain visible and are reported per task; successful items move to **已删除**.

The **已删除** page supports multi-select **恢复所选**. Physical purge is intentionally out of scope.

## Task detail and result viewing

Every task card is clickable and opens a fixed task-detail surface inside the existing WPF application.

The detail surface always shows:

- task title/type
- current status
- created/updated timestamps
- attempt count
- task goal or safe payload summary
- error summary when present

If a result exists, the same detail surface loads the fixed result contract for that task type.

Supported result renderers in this change:

- `system.diagnostic_snapshot`: existing diagnostic renderer
- `research.search`: Research result renderer with query, summary/content, source list, and source URLs

Unknown result types remain metadata-only and never fall back to arbitrary file/path browsing.

## Windows typography and DPI readability

The entire WPF program uses one shared typography scale instead of scattered tiny font sizes.

### Typography tokens

Application resources define centralized sizes:

- Caption: 12 DIP
- Secondary/body-small: 13 DIP
- Body: 14 DIP
- Emphasized body: 15 DIP
- Section heading: 18 DIP
- Page heading: 26 DIP

Existing controls with smaller values are migrated to these tokens unless a layout-specific exception is required for clipping prevention.

### Rendering rules

- Keep WPF device-independent units; do not emulate scaling with layout transforms.
- Enable per-monitor DPI awareness through the existing application manifest/runtime configuration.
- Use `TextOptions.TextFormattingMode="Display"` for operator UI text where pixel-snapped glyph rendering is preferable.
- Use `TextOptions.TextRenderingMode="ClearType"` on opaque application surfaces; do not force ClearType on transparent floating-pet surfaces.
- Keep fractional layout values out of primary text containers where possible; use whole-DIP padding/margins for text-heavy surfaces.
- Increase minimum button height and card vertical padding so larger text does not crowd controls.

## Navigation

Simple mode becomes six primary entries:

- 首页
- 待我审核
- 进行中
- 已完成
- 已删除
- 高级

The new **已删除** route is visible whenever durable task history is available.

## Error handling

- Safe delete never silently removes an active task. Cancellation/visibility results are returned per task.
- If Mac Core is unreachable, selection remains intact and the user sees a recoverable error.
- Result-loading failures do not remove the task card; the detail page shows a safe error summary.
- Restore failures leave the task in **已删除**.

## Compatibility and safety constraints

- Main Windows product identity remains the approved 2.3.26.1 identity; Research capability remains 2.3.27.1.
- Mac Core remains authoritative.
- No arbitrary shell execution is added.
- No physical task/result deletion is added.
- Existing diagnostic OpenAPI/result contract remains unchanged.
- Existing Research read-only/write-disabled policy remains unchanged.
- Existing Maotai/pet UI work is preserved.

## Acceptance criteria

1. A completed task can be selected, safely deleted, disappears from **已完成**, appears in **已删除**, and can be restored.
2. An active task can be safely deleted only through cancel-then-hide behavior; it is never physically removed.
3. Multiple visible tasks can be selected and deleted in one operation with per-task outcomes.
4. Multiple deleted tasks can be selected and restored.
5. Every task card opens task detail.
6. Diagnostic and Research tasks with results show their fixed-contract result content in Windows.
7. Unknown result types do not expose arbitrary files, paths, or raw manifests.
8. Primary Windows text is legible at 100%, 125%, 150%, and 200% scaling with no intentionally tiny 8–10 DIP operator text remaining on normal pages.
9. Existing WPF tests, Research contracts, target-integrity checks, and Windows release lifecycle remain green.
