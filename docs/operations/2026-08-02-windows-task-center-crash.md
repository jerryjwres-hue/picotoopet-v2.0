# Windows Task Center navigation crash — 2026-08-02

## Field symptom

On Windows Control Center Slice B, the Mac connection and other pages remain usable. Selecting **任务中心** freezes the window briefly and terminates `Picotoo Pet AI.exe`.

## Verified environment

- Installed Windows candidate: `2.3.0-slice-b-86-1ac93e8c5658918aa9590184ead8f2e286a06189`
- Windows: `Microsoft Windows NT 10.0.26200.0`, x64
- Mac Core and Worker were running and TCP `192.168.1.161:8766` was reachable before reproducing the UI crash.

## Root cause evidence

Windows `.NET Runtime` event 1026 recorded:

```text
System.InvalidOperationException:
无法对“PicotooPet.Desktop.ViewModels.TaskRowViewModel”类型的只读属性“Priority”进行 TwoWay 或 OneWayToSource 绑定。
```

The exception originates from WPF `PropertyPathWorker.CheckReadOnly` while materializing the Task Center detail view. `TaskRowViewModel.Priority` and `TimeoutSeconds` are read-only presentation properties, while their `Run.Text` bindings did not declare `Mode=OneWay` explicitly.

The application did not register `DispatcherUnhandledException`, so the UI-thread binding exception terminated the whole process.

## Permanent release gates

1. Every binding from `Run.Text` to a read-only ViewModel property must declare `Mode=OneWay`.
2. The real Task Center WPF page must be instantiated and laid out in a native Windows UI smoke test; ViewModel-only smoke tests are insufficient.
3. The WPF dispatcher must log unhandled exceptions to `desktop.log` and contain non-fatal page-rendering exceptions instead of terminating the entire Control Center.
4. A Windows candidate may not be delivered until clicking Task Center succeeds against an empty queue and a queue containing at least one task.
5. Diagnostic collectors may print `PASS` only after the final archive exists, has non-zero size and has a computed SHA-256.

## Safety

- No Mac reinstall or rollback is required.
- No token rotation is required.
- Existing tasks and the Mac database are unaffected.
- Until a natively verified Windows repair package is available, users should avoid opening Task Center.
