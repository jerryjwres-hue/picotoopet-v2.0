using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>确保原生任务中心动作按钮与 Mac Core 的诊断状态机一致。</summary>
internal static class DiagnosticTaskActionStateSmokeTests
{
    private static readonly string[] SupportedDiagnosticTaskTypes =
    {
        "system.diagnostic_snapshot",
        "system.noop",
    };

    public static void Run()
    {
        var now = new DateTimeOffset(2026, 8, 3, 12, 0, 0, TimeSpan.Zero);
        var worker = new WorkerSnapshot(
            SchemaVersion: "2.3.0",
            Available: true,
            State: "online",
            Reason: "idle",
            WorkerId: "worker-m4",
            SupportedTaskTypes: SupportedDiagnosticTaskTypes,
            ObservedAt: now);

        var diagnosticRetrying = CreateTask(
            taskId: "diagnostic-retrying",
            taskType: "system.diagnostic_snapshot",
            status: "Retrying",
            now: now);
        var diagnosticRunning = diagnosticRetrying with
        {
            TaskId = "diagnostic-running",
            Status = "Running",
        };
        var ordinaryRetrying = diagnosticRetrying with
        {
            TaskId = "ordinary-retrying",
            TaskType = "analysis",
        };

        var retryingDiagnosticRow = TaskRowViewModel.FromRecord(
            diagnosticRetrying,
            worker);
        var runningDiagnosticRow = TaskRowViewModel.FromRecord(
            diagnosticRunning,
            worker);
        var ordinaryRetryingRow = TaskRowViewModel.FromRecord(
            ordinaryRetrying,
            worker);

        SmokeAssert.True(
            !retryingDiagnosticRow.CanCancel,
            "诊断 Retrying 不能启用取消；服务端只接受 Queued/Running");
        SmokeAssert.True(
            runningDiagnosticRow.CanCancel,
            "诊断 Running 必须允许提交安全取消意图");
        SmokeAssert.True(
            ordinaryRetryingRow.CanCancel,
            "非诊断任务必须保留既有 Retrying 取消行为");
    }

    private static TaskRecord CreateTask(
        string taskId,
        string taskType,
        string status,
        DateTimeOffset now) => new(
        TaskId: taskId,
        ParentTaskId: null,
        ProjectId: null,
        TaskType: taskType,
        Status: status,
        Priority: 50,
        ResourceTag: "system-diagnostic",
        Payload: JsonSerializer.SerializeToElement(new { schema_version = "1.0" }),
        AttemptCount: 1,
        MaxAttempts: 2,
        TimeoutSeconds: 30,
        CreatedAt: now,
        UpdatedAt: now,
        ErrorCode: null,
        ErrorMessage: null,
        ResultId: null);
}
