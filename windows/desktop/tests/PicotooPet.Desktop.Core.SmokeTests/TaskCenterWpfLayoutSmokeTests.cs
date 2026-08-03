using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 页面上验证任务中心绑定可以完成布局。</summary>
internal static class TaskCenterWpfLayoutSmokeTests
{
    /// <summary>构造含只读优先级和超时字段的页面，并执行完整布局流水线。</summary>
    public static void Run()
    {
        var timestamp = new DateTimeOffset(2026, 8, 2, 20, 0, 0, TimeSpan.Zero);
        var task      = new TaskRecord(
            TaskId: "task-center-layout-regression",
            ParentTaskId: null,
            ProjectId: "project-layout-regression",
            TaskType: "analysis",
            Status: "Queued",
            Priority: 100,
            ResourceTag: null,
            Payload: JsonSerializer.SerializeToElement(new { prompt = "layout fixture" }),
            AttemptCount: 0,
            MaxAttempts: 3,
            TimeoutSeconds: 3600,
            CreatedAt: timestamp,
            UpdatedAt: timestamp,
            ErrorCode: null,
            ErrorMessage: null);
        var viewModel = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { task },
            WorkerSnapshot.NotDeployed);
        var page = new TaskCenterPage
        {
            DataContext = viewModel,
        };

        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(page.IsMeasureValid, "Task Center Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Task Center Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Task Center 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Task Center 实际高度无效");
    }
}
