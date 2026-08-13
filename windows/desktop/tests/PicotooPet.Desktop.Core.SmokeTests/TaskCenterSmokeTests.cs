using System.Reflection;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证任务中心的真实状态解释、安全动作策略和逻辑任务选择稳定性。</summary>
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

        VerifyDiagnosticResultSurvivesSameTaskSnapshotRefresh(createdAt);
    }

    /// <summary>同一 task_id 的后台快照刷新不得被当作用户切换任务。</summary>
    private static void VerifyDiagnosticResultSurvivesSameTaskSnapshotRefresh(DateTimeOffset createdAt)
    {
        var diagnostic = CreateTask("diagnostic-stable", "Completed", createdAt) with
        {
            TaskType = "system.diagnostic_snapshot",
            ResultId = "diagnostic-result-1",
        };
        var other = CreateTask("other-task", "Completed", createdAt);
        var worker = WorkerSnapshot.NotDeployed;
        var page = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { diagnostic, other },
            worker);

        SmokeAssert.Equal("diagnostic-stable", page.SelectedTask?.TaskId, "诊断任务未成为初始选择");
        SetDiagnosticCard(page);
        SmokeAssert.True(page.IsDiagnosticResultVisible, "测试夹具未显示诊断结果卡");

        InvokeApplySnapshot(
            page,
            new[]
            {
                diagnostic with { UpdatedAt = createdAt.AddSeconds(1) },
                other,
            },
            worker);

        SmokeAssert.Equal(
            "diagnostic-stable",
            page.SelectedTask?.TaskId,
            "同一 task_id 刷新后逻辑选择丢失");
        SmokeAssert.True(
            page.IsDiagnosticResultVisible,
            "同一 task_id 仅因后台 snapshot 重建行对象就清空了诊断结果卡");
        SmokeAssert.True(
            page.DiagnosticResult is not null,
            "同一 task_id 刷新后诊断结果对象被错误清空");

        page.SelectedTask = page.VisibleTasks.Single(task => task.TaskId == "other-task");
        SmokeAssert.True(
            !page.IsDiagnosticResultVisible && page.DiagnosticResult is null,
            "用户真正切换到其他 task_id 后诊断结果卡应清空");
    }

    /// <summary>仅用于烟测构造一张已加载的固定诊断结果卡。</summary>
    private static void SetDiagnosticCard(TaskCenterPageViewModel page)
    {
        var resultProperty = typeof(TaskCenterPageViewModel).GetProperty(
            nameof(TaskCenterPageViewModel.DiagnosticResult),
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("DiagnosticResult 属性不存在。");
        var visibleProperty = typeof(TaskCenterPageViewModel).GetProperty(
            nameof(TaskCenterPageViewModel.IsDiagnosticResultVisible),
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("IsDiagnosticResultVisible 属性不存在。");

        resultProperty.SetValue(page, DiagnosticResultViewModel.FromError("fixture diagnostic card"));
        visibleProperty.SetValue(page, true);
    }

    /// <summary>通过私有快照入口复现 Session 更新，避免为测试扩大产品 API。</summary>
    private static void InvokeApplySnapshot(
        TaskCenterPageViewModel page,
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker)
    {
        var method = typeof(TaskCenterPageViewModel).GetMethod(
            "ApplySnapshot",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("ApplySnapshot 方法不存在。");
        method.Invoke(page, new object[] { tasks, worker });
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