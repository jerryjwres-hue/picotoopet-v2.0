using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证结果中心只列出真实终态结果、保持筛选和安全预览边界。</summary>
internal static class ResultsCenterSmokeTests
{
    public static void Run()
    {
        var older = CreateTask(
            "diagnostic-old",
            "system.diagnostic_snapshot",
            "Completed",
            "result-old",
            new DateTimeOffset(2026, 8, 4, 20, 0, 0, TimeSpan.Zero));
        var newer = CreateTask(
            "diagnostic-new",
            "system.diagnostic_snapshot",
            "Completed",
            "result-new",
            new DateTimeOffset(2026, 8, 5, 1, 0, 0, TimeSpan.Zero));
        var archived = CreateTask(
            "archived-result",
            "system.diagnostic_snapshot",
            "Archived",
            "result-archived",
            new DateTimeOffset(2026, 8, 3, 18, 0, 0, TimeSpan.Zero));
        var queued = CreateTask(
            "queued-analysis",
            "analysis",
            "Queued",
            null,
            new DateTimeOffset(2026, 8, 1, 2, 22, 1, TimeSpan.Zero));
        var completedWithoutResult = CreateTask(
            "completed-without-result",
            "analysis",
            "Completed",
            null,
            new DateTimeOffset(2026, 8, 2, 2, 22, 1, TimeSpan.Zero));

        var viewModel = ResultsPageViewModel.CreateForSmokeTest(
            new[] { older, newer, archived, queued, completedWithoutResult });

        SmokeAssert.Equal(3, viewModel.AllResults.Count, "结果中心包含无结果或非终态任务");
        SmokeAssert.Equal("diagnostic-new", viewModel.AllResults[0].TaskId, "结果没有按更新时间倒序");
        SmokeAssert.True(viewModel.AllResults.All(row => row.CanPreview), "诊断结果应允许固定安全预览");

        viewModel.SelectedFilter = ResultsFilter.Archived;
        SmokeAssert.Equal(1, viewModel.VisibleResults.Count, "归档筛选错误");
        SmokeAssert.Equal("archived-result", viewModel.VisibleResults[0].TaskId, "归档结果错误");

        viewModel.SelectedFilter = ResultsFilter.Diagnostic;
        SmokeAssert.Equal(3, viewModel.VisibleResults.Count, "系统诊断筛选错误");
        viewModel.SelectedResult = viewModel.VisibleResults[0];
        SmokeAssert.True(viewModel.CanLoadSelectedPreview, "可预览结果未启用动作");

        var unknown = ResultRowViewModel.FromRecord(CreateTask(
            "unknown-result",
            "future.result_type",
            "Completed",
            "result-unknown",
            new DateTimeOffset(2026, 8, 5, 2, 0, 0, TimeSpan.Zero)));
        SmokeAssert.False(unknown.CanPreview, "未知结果类型不得回退到通用预览");
        SmokeAssert.True(
            unknown.PreviewUnavailableReason.Contains("尚不支持", StringComparison.Ordinal),
            "未知结果类型缺少安全说明");
    }

    private static TaskRecord CreateTask(
        string taskId,
        string taskType,
        string status,
        string? resultId,
        DateTimeOffset updatedAt) => new(
            TaskId: taskId,
            ParentTaskId: null,
            ProjectId: null,
            TaskType: taskType,
            Status: status,
            Priority: 100,
            ResourceTag: null,
            Payload: JsonSerializer.SerializeToElement(new { }),
            AttemptCount: 1,
            MaxAttempts: 2,
            TimeoutSeconds: 30,
            CreatedAt: updatedAt.AddMinutes(-1),
            UpdatedAt: updatedAt,
            ErrorCode: null,
            ErrorMessage: null,
            ResultId: resultId);
}
