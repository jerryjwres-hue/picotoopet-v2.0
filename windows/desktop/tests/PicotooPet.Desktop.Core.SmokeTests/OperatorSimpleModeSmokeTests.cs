using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.27.1 六入口导航、任务可恢复隐藏投影、受控 Research 向导和 STA WPF 布局。</summary>
internal static class OperatorSimpleModeSmokeTests
{
    private static readonly string[] ReviewTaskIds = new[] { "review" };
    private static readonly string[] InProgressTaskIds = new[] { "running" };
    private static readonly string[] CompletedTaskIds = new[] { "done" };
    private static readonly string[] DeletedTaskIds = new[] { "deleted" };
    private static readonly string[] SupportedTaskTypes = new[]
    {
        "system.diagnostic_snapshot",
        "business.local_intelligence.v1",
        "creative.content_plan.v1",
        "research.search",
    };

    public static void Run()
    {
        VerifyNavigation();
        VerifyProjectionAndWizard();
        VerifyWpfLayout();
    }

    private static void VerifyNavigation()
    {
        using var shell = ShellViewModel.CreateForSmokeTest(FullCapabilities());
        var expected = new[] { "首页", "待我审核", "进行中", "已完成", "已删除", "高级" };
        SmokeAssert.True(shell.NavigationItems.Count == expected.Length, "2.3.27.1 默认导航必须恰好六项");
        SmokeAssert.True(
            shell.NavigationItems.Select(item => item.Title).SequenceEqual(expected),
            "2.3.27.1 默认导航顺序错误");
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.OperatorHome, "2.3.27.1 必须默认进入首页");

        shell.Navigate(NavigationRoute.OperatorDeleted);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.OperatorDeleted, "已删除简单路由必须保留");
        shell.Navigate(NavigationRoute.BusinessAutomation);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.BusinessAutomation, "高级业务自动化路由必须保留");
        SmokeAssert.True(shell.SelectedNavigationItem.Route == NavigationRoute.AdvancedHome, "高级子页面必须保持高级入口选中");
        shell.Navigate(NavigationRoute.Settings);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.Settings, "设置高级路由必须保留");
    }

    private static void VerifyProjectionAndWizard()
    {
        var now = DateTimeOffset.UtcNow;
        var snapshot = Snapshot(
            Task("review", "business.local_intelligence.v1", "NeedsHuman", now.AddMinutes(-1)),
            Task("running", "creative.content_plan.v1", "Running", now),
            Task("done", "system.diagnostic_snapshot", "Completed", now.AddMinutes(-2), resultId: "result-1"),
            Task("deleted", "research.search", "Completed", now.AddMinutes(-3), resultId: "result-2", isHidden: true));
        var projection = OperatorProjection.FromSnapshot(snapshot);

        SmokeAssert.True(projection.PendingReview.Select(item => item.TaskId).SequenceEqual(ReviewTaskIds), "审核桶分类错误");
        SmokeAssert.True(projection.InProgress.Select(item => item.TaskId).SequenceEqual(InProgressTaskIds), "进行中分类错误");
        SmokeAssert.True(projection.Completed.Select(item => item.TaskId).SequenceEqual(CompletedTaskIds), "完成桶分类错误");
        SmokeAssert.True(projection.Deleted.Select(item => item.TaskId).SequenceEqual(DeletedTaskIds), "已删除桶分类错误");
        SmokeAssert.True(!projection.Completed.Any(item => item.TaskId == "deleted"), "隐藏任务不得继续出现在已完成");
        SmokeAssert.True(projection.CoreStatus == "在线", "Core 简单状态错误");
        SmokeAssert.True(projection.WorkerStatus.Contains("空闲", StringComparison.Ordinal), "Worker 简单状态错误");

        var forbiddenProjectionNames = new[] { "Provider", "Endpoint", "ApiKey", "Model", "Prompt", "Workflow", "Command", "Sql", "Percentage", "Percent" };
        var projectionProperties = typeof(OperatorProjection).GetProperties(BindingFlags.Public | BindingFlags.Instance)
            .Select(property => property.Name)
            .Concat(typeof(OperatorTaskCard).GetProperties(BindingFlags.Public | BindingFlags.Instance).Select(property => property.Name))
            .ToArray();
        foreach (var forbidden in forbiddenProjectionNames)
        {
            SmokeAssert.True(!projectionProperties.Any(name => name.Contains(forbidden, StringComparison.OrdinalIgnoreCase)), $"OperatorProjection 暴露禁止字段 {forbidden}");
        }

        var wizard = NewTaskWizardViewModel.CreateForSmokeTest();
        SmokeAssert.True(wizard.Options.Count == 4, "任务向导必须是有限选项集合");
        var web = wizard.Options.Single(option => option.Kind == OperatorTaskKind.WebResearch);
        SmokeAssert.True(web.IsAvailable && web.AvailabilityText == "可用", "Research Adapter 接入后网络调研必须可用");
        SmokeAssert.True(wizard.CanGoNext, "默认真实任务应允许进入第二步");
        wizard.Next();
        SmokeAssert.True(wizard.CanGoBack && wizard.CanSubmit, "向导第二步状态错误");
        wizard.Back();
        SmokeAssert.True(wizard.Step == 1, "向导返回状态错误");

        var forbiddenWizardNames = new[] { "Provider", "Endpoint", "ApiKey", "Model", "Prompt", "Workflow", "Command", "Sql", "Budget" };
        var wizardProperties = typeof(NewTaskWizardViewModel).GetProperties(BindingFlags.Public | BindingFlags.Instance)
            .Select(property => property.Name)
            .ToArray();
        foreach (var forbidden in forbiddenWizardNames)
        {
            SmokeAssert.True(!wizardProperties.Any(name => name.Contains(forbidden, StringComparison.OrdinalIgnoreCase)), $"任务向导暴露禁止字段 {forbidden}");
        }
    }

    private static void VerifyWpfLayout()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var snapshot = Snapshot(
                    Task("running", "business.local_intelligence.v1", "Running", DateTimeOffset.UtcNow),
                    Task("done", "system.diagnostic_snapshot", "Completed", DateTimeOffset.UtcNow.AddMinutes(-1), resultId: "result-1"),
                    Task("deleted", "research.search", "Completed", DateTimeOffset.UtcNow.AddMinutes(-2), resultId: "result-2", isHidden: true));
                var homeViewModel = OperatorHomePageViewModel.CreateForSmokeTest(snapshot);
                var activeViewModel = new OperatorTaskListPageViewModel("进行中", completed: false, snapshot);
                var completedViewModel = new OperatorTaskListPageViewModel("已完成", completed: true, snapshot);
                var reviewViewModel = OperatorReviewPageViewModel.CreateForSmokeTest();

                Layout(new OperatorHomePage { DataContext = homeViewModel });
                Layout(new OperatorTaskListPage { DataContext = activeViewModel });
                Layout(new OperatorTaskListPage { DataContext = completedViewModel });
                Layout(new OperatorReviewPage { DataContext = reviewViewModel });

                var refreshed = Snapshot(
                    Task("running", "business.local_intelligence.v1", "Running", DateTimeOffset.UtcNow.AddSeconds(10)),
                    Task("done", "system.diagnostic_snapshot", "Completed", DateTimeOffset.UtcNow.AddSeconds(9), resultId: "result-1"));
                homeViewModel.UpdateSnapshot(refreshed);
                activeViewModel.UpdateSnapshot(refreshed);
                completedViewModel.UpdateSnapshot(refreshed);
                SmokeAssert.True(activeViewModel.Items.Single().TaskId == "running", "同 task_id 快照刷新后进行中卡片身份丢失");
                SmokeAssert.True(completedViewModel.Items.Single().TaskId == "done", "同 task_id 快照刷新后完成卡片身份丢失");
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static void Layout(FrameworkElement element)
    {
        element.Measure(new Size(1100, 800));
        element.Arrange(new Rect(0, 0, 1100, 800));
        element.UpdateLayout();
        element.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        element.UpdateLayout();
        SmokeAssert.True(element.IsMeasureValid, $"{element.GetType().Name} Measure 未完成");
        SmokeAssert.True(element.IsArrangeValid, $"{element.GetType().Name} Arrange 未完成");
    }

    private static ControlCenterSessionSnapshot Snapshot(params TaskRecord[] tasks)
    {
        var capabilities = FullCapabilities();
        var state = new ControlCenterSnapshot(
            new ConnectionSnapshot(ConnectionState.Online, null),
            new CapabilitySnapshot(
                "2.3.0",
                capabilities,
                new ContractVersions("1.0", "1.0", "1.0"),
                "manual_approval_only"),
            new WorkerSnapshot(
                "2.3.0",
                true,
                "online",
                "idle",
                "worker-smoke",
                SupportedTaskTypes,
                DateTimeOffset.UtcNow),
            new TaskStateSnapshot(tasks, 1, false, tasks.LastOrDefault()));
        return new ControlCenterSessionSnapshot(
            "http://127.0.0.1:8765",
            state,
            "ok · 2.3.27.1",
            "REST p95 1 ms",
            "双机控制链已连接。");
    }

    private static TaskRecord Task(
        string id,
        string type,
        string status,
        DateTimeOffset updatedAt,
        string? resultId = null,
        bool isHidden = false)
    {
        var payload = type == "research.search"
            ? JsonSerializer.SerializeToElement(new { query = "测试查询" })
            : JsonSerializer.SerializeToElement(new { });
        return new TaskRecord(
            id,
            null,
            null,
            type,
            status,
            100,
            null,
            payload,
            0,
            3,
            3600,
            updatedAt.AddMinutes(-1),
            updatedAt,
            null,
            null,
            resultId,
            isHidden);
    }

    private static ControlCenterCapabilities FullCapabilities() => new(
        LocalAgent: true,
        DurableQueue: true,
        McpHub: true,
        Dashboard: true,
        TaskDetail: true,
        TaskPauseResume: true,
        ApprovalList: true,
        ApprovalDigest: true,
        ResultList: true,
        ResultPreview: true,
        HealthDetailed: true,
        LogsQuery: true,
        ManualGoal: true,
        ConnectorContractV1: true,
        HandoffContractV1: true,
        WorkerStatus: true,
        LocalWorker: true,
        WindowsWorker: false,
        Projects: true,
        WorkflowAutomation: true,
        AutomationHealth: true,
        AutomationDiagnostics: true);
}
