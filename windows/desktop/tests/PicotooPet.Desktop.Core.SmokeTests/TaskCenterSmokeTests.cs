using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证任务中心的真实状态解释和安全动作策略。</summary>
internal static class TaskCenterSmokeTests
{
    public static void Run()
    {
        var createdAt = new DateTimeOffset(2026, 8, 1, 0, 0, 0, TimeSpan.Zero);
        var queued = CreateTask("queued-old", "Queued", createdAt);
        var failed = CreateTask("failed-1", "Failed", createdAt);
        var cancelled = CreateTask("cancelled-1", "Cancelled", createdAt);
        var completed = CreateTask("completed-1", "Completed", createdAt);
        var worker = WorkerSnapshot.NotDeployed;

        var queuedRow = TaskRowViewModel.FromRecord(queued, worker);
        SmokeAssert.Equal("等待执行器", queuedRow.DisplayStatus, "未部署 Worker 时 Queued 状态解释错误");
        SmokeAssert.True(queuedRow.IsWaitingForWorker, "历史 Queued 任务未标记等待执行器");
        SmokeAssert.True(queuedRow.CanCancel, "Queued 任务应允许安全取消");
        SmokeAssert.True(!queuedRow.CanRetry, "Queued 任务不得重试");

        var failedRow = TaskRowViewModel.FromRecord(failed, worker);
        SmokeAssert.True(!failedRow.CanCancel, "Failed 终态不得取消");
        SmokeAssert.True(failedRow.CanRetry, "Failed 任务应允许创建子任务重试");

        var cancelledRow = TaskRowViewModel.FromRecord(cancelled, worker);
        SmokeAssert.True(!cancelledRow.CanCancel, "Cancelled 终态不得再次取消");
        SmokeAssert.True(cancelledRow.CanRetry, "Cancelled 任务应允许创建子任务重试");

        var completedRow = TaskRowViewModel.FromRecord(completed, worker);
        SmokeAssert.True(!completedRow.CanCancel, "Completed 终态不得取消");
        SmokeAssert.True(!completedRow.CanRetry, "Completed 任务不得重试");

        var page = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { queued, failed, completed },
            worker);
        page.SelectedFilter = TaskCenterFilter.WaitingForWorker;
        SmokeAssert.Equal(1, page.VisibleTasks.Count, "等待执行器筛选结果错误");
        SmokeAssert.Equal("queued-old", page.VisibleTasks[0].TaskId, "等待执行器筛选任务错误");
    }

    private static TaskRecord CreateTask(
        string taskId,
        string status,
        DateTimeOffset createdAt) => new(
            TaskId: taskId,
            ParentTaskId: null,
            ProjectId: null,
            TaskType: "analysis",
            Status: status,
            Priority: 100,
            ResourceTag: null,
            Payload: JsonSerializer.SerializeToElement(new { prompt = "fixture" }),
            AttemptCount: status == "Failed" ? 1 : 0,
            MaxAttempts: 3,
            TimeoutSeconds: 3600,
            CreatedAt: createdAt,
            UpdatedAt: createdAt,
            ErrorCode: status == "Failed" ? "FIXTURE_FAILURE" : null,
            ErrorMessage: status == "Failed" ? "fixture failure" : null);
}
