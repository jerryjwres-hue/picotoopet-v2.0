using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.27.1 六入口导航、目标中心、任务可恢复隐藏投影和 STA WPF 布局。</summary>
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
        VerifyGoalCenterClientContract();
        VerifyMoutaiSceneGoalAssistance();
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

    /// <summary>目标中心必须走 Mac Core 的固定 Goal/Handoff API，不能在 Windows 自造工作流。</summary>
    private static void VerifyGoalCenterClientContract()
    {
        var methods = typeof(MacCoreClient)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Select(method => method.Name)
            .ToHashSet(StringComparer.Ordinal);
        var required = new[]
        {
            "GetGoalTemplatesAsync",
            "GetGoalsAsync",
            "GetGoalAsync",
            "CreateGoalAsync",
            "GetGoalHandoffAsync",
            "DownloadGoalHandoffAsync",
            "GetGoalHandoffPromptAsync",
        };
        foreach (var method in required)
        {
            SmokeAssert.True(methods.Contains(method), $"MacCoreClient 缺少 Goal Center 固定调用：{method}");
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

                var homePage = new OperatorHomePage { DataContext = homeViewModel };
                Layout(homePage);
                // Regression: a narrow handoff card must wrap the Web GPT paste
                // action instead of placing it beyond the clipped right edge.
                var goalPanel = new GoalCenterPanel { DataContext = homeViewModel };
                Layout(goalPanel);
                var pasteReturn = goalPanel.FindName("PasteGoalVideoReturnButton") as Button;
                var copyPrompt = goalPanel.FindName("CopyPromptButton") as Button;
                var saveHandoff = goalPanel.FindName("SaveHandoffButton") as Button;
                SmokeAssert.True(pasteReturn?.Parent is WrapPanel actions
                    && ReferenceEquals(copyPrompt?.Parent, actions)
                    && ReferenceEquals(saveHandoff?.Parent, actions),
                    "The Web GPT paste action must share a wrapping container with the handoff actions");

                SmokeAssert.True(goalPanel.FindName("MoutaiSceneSection") is FrameworkElement, "GoalCenterPanel 缺少茅台场景创作区");
                SmokeAssert.True(goalPanel.FindName("MoutaiSceneItems") is ItemsControl, "GoalCenterPanel 缺少茅台场景选择控件");
                SmokeAssert.True(homePage.FindName("GoalObjectiveTextBox") is TextBox, "首页缺少目标输入框");
                SmokeAssert.True(homePage.FindName("GoalTemplateItems") is ItemsControl, "首页缺少建议目标模板");
                SmokeAssert.True(homePage.FindName("GoalDepthComboBox") is ComboBox, "首页缺少研究深度选择");
                SmokeAssert.True(homePage.FindName("CreateGoalButton") is Button, "首页缺少发送目标按钮");
                SmokeAssert.True(homePage.FindName("GoalStatusCard") is FrameworkElement, "首页缺少目标自动执行状态区");

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

    public static void RunMoutaiSceneOnly()
    {
        VerifyMoutaiSceneGoalAssistance();
        VerifyMoutaiSceneWpfLayout();
    }

    private static void VerifyMoutaiSceneGoalAssistance()
    {
        var snapshot = Snapshot();
        var homeViewModel = OperatorHomePageViewModel.CreateForSmokeTest(snapshot);

        // 1. 验证四种预设场景
        var scenes = homeViewModel.MoutaiScenes;
        SmokeAssert.True(scenes.Count == 4, "茅台场景预设必须恰好四项");
        var expectedTitles = new[] { "日常生活", "出行旅游", "饮食生活", "宠物用品" };
        var expectedKeys = new[] { "DailyLife", "Travel", "Dining", "Supplies" };
        SmokeAssert.True(scenes.Select(s => s.Title).SequenceEqual(expectedTitles), "场景中文标题不匹配");
        SmokeAssert.True(scenes.Select(s => s.Key).SequenceEqual(expectedKeys), "场景键名不匹配");

        // 2. 检查草稿内容规范性
        foreach (var scene in scenes)
        {
            SmokeAssert.True(!string.IsNullOrWhiteSpace(scene.Description), $"{scene.Title} 缺少描述");
            SmokeAssert.True(scene.DraftObjective.Contains("茅台", StringComparison.Ordinal), $"{scene.Title} 未明确主角茅台");
            SmokeAssert.True(scene.DraftObjective.Contains("鼻纹", StringComparison.Ordinal), $"{scene.Title} 未强调独特鼻纹特征");
            SmokeAssert.True(scene.DraftObjective.Contains("HOOK", StringComparison.Ordinal)
                && scene.DraftObjective.Contains("ACTION", StringComparison.Ordinal)
                && scene.DraftObjective.Contains("PAYOFF", StringComparison.Ordinal),
                $"{scene.Title} 未遵循 HOOK → ACTION → PAYOFF 剧情结构");
            SmokeAssert.True(scene.DraftObjective.Contains("镜头1")
                && scene.DraftObjective.Contains("镜头2")
                && scene.DraftObjective.Contains("镜头3"),
                $"{scene.Title} 未包含推荐的三镜头规划");
            SmokeAssert.True(scene.DraftObjective.Length >= 4 && scene.DraftObjective.Length <= 2000,
                $"{scene.Title} 草稿长度超出边界");

            // 规则6：透明恢复圈、绿色围巾不得默认强制佩戴
            SmokeAssert.True(scene.DraftObjective.Contains("无伊丽莎白圈") || scene.DraftObjective.Contains("无临时"),
                $"{scene.Title} 必须明确无临时项圈或围巾佩戴要求");
        }

        // 宠物用品场景质控：不能编造品牌、材质、功能或营销宣称
        var suppliesScene = scenes.Single(s => s.Key == "Supplies");
        SmokeAssert.True(suppliesScene.DraftObjective.Contains("严禁虚构品牌")
            && suppliesScene.DraftObjective.Contains("营销宣称"),
            "宠物用品草稿必须明确禁止编造虚假品牌与营销宣称");

        // 3. 选择场景只更新草稿，不自造 Goal、不自动提交、不触发忙状态
        var daily = scenes.Single(s => s.Key == "DailyLife");
        homeViewModel.SelectMoutaiScene(daily);
        SmokeAssert.True(homeViewModel.SelectedMoutaiScene?.Key == "DailyLife", "选中场景状态未记录");
        SmokeAssert.True(homeViewModel.GoalObjective == daily.DraftObjective, "选择场景未填入对应草稿");
        SmokeAssert.True(!homeViewModel.IsGoalBusy, "选择场景不得自动触发提交或忙状态");
        SmokeAssert.True(homeViewModel.CurrentGoal is null, "选择场景不得自动生成服务端目标");
        SmokeAssert.True(homeViewModel.SelectedGoalType == "video.creative", "选择场景必须对齐 Mac Core 视频模板");

        // 4. 用户手动自由编辑，内容不被意外覆盖
        var customEdited = "【茅台自定镜头】1. 茅台在草地上抬头看云；2. 茅台小跑；3. 茅台开心坐下。保持黑白灰毛色与鼻纹一致。";
        homeViewModel.GoalObjective = customEdited;
        SmokeAssert.True(homeViewModel.GoalObjective == customEdited, "用户编辑内容丢失");
        SmokeAssert.True(!string.IsNullOrWhiteSpace(homeViewModel.SelectedGoalType) && homeViewModel.GoalObjective.Trim().Length is >= 4 and <= 2000, "合法自定义编辑后草稿与模板校验应通过");

        // 刷新快照不得覆盖用户正在编辑的草稿
        var refreshed = Snapshot(Task("running", "creative.content_plan.v1", "Running", DateTimeOffset.UtcNow));
        homeViewModel.UpdateSnapshot(refreshed);
        SmokeAssert.True(homeViewModel.GoalObjective == customEdited, "快照刷新意外覆盖了用户的编辑内容");

        // 5. 切换到其他场景正常更新草稿
        var travel = scenes.Single(s => s.Key == "Travel");
        homeViewModel.SelectMoutaiScene(travel);
        SmokeAssert.True(homeViewModel.GoalObjective == travel.DraftObjective, "切换场景未更新草稿");
        SmokeAssert.True(homeViewModel.SelectedMoutaiScene?.Key == "Travel", "切换场景未更新选中态");
    }

    private static void VerifyMoutaiSceneWpfLayout()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var snapshot = Snapshot();
                var homeViewModel = OperatorHomePageViewModel.CreateForSmokeTest(snapshot);
                var goalPanel = new GoalCenterPanel { DataContext = homeViewModel };
                Layout(goalPanel);

                SmokeAssert.True(goalPanel.FindName("MoutaiSceneSection") is FrameworkElement, "GoalCenterPanel 缺少茅台场景创作区");
                SmokeAssert.True(goalPanel.FindName("MoutaiSceneItems") is ItemsControl, "GoalCenterPanel 缺少茅台场景 ItemsControl");

                var homePage = new OperatorHomePage { DataContext = homeViewModel };
                Layout(homePage);
                var embedded = (homePage.FindName("HeroCard") as Border)?.Child as GoalCenterPanel;
                SmokeAssert.True(embedded?.FindName("MoutaiSceneSection") is FrameworkElement, "首页嵌入的 GoalCenterPanel 缺少茅台场景创作区");
                SmokeAssert.True(embedded?.FindName("MoutaiSceneItems") is ItemsControl, "首页嵌入的 GoalCenterPanel 缺少茅台场景 ItemsControl");
            }
            catch (Exception ex)
            {
                failure = ex;
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
