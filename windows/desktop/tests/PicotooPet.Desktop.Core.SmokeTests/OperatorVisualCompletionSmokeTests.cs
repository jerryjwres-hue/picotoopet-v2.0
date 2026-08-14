using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Controls;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 26.1 Visual Completion 的助手状态、组件白名单和产品化 WPF 表面。</summary>
internal static class OperatorVisualCompletionSmokeTests
{
    private static readonly string[] ExpectedWidgetIds =
    {
        "search-insight",          // 搜索洞察：保留未来接入位，但当前必须禁用。
        "comment-analysis",        // 评论分析：映射既有本地智能能力，不扩张权限。
        "video-creation",          // 视频创作：只展示既有生产任务事实。
        "content-generation",      // 内容生成：映射既有创意任务事实。
        "result-optimization",     // 结果优化：只展示既有质量治理事实。
    };

    public static void Run()
    {
        VerifyAssistantStateResolver();
        VerifyClosedWidgetCatalog();
        VerifyLayoutNormalization();
        VerifyProductizedWpfSurfaces();
    }

    private static void VerifyAssistantStateResolver()
    {
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: true, hasActiveTask: true)
                == OperatorAssistantVisualState.Working,
            "在线且有活动任务时，阿拉斯加必须进入工作状态");
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: true, hasActiveTask: false)
                == OperatorAssistantVisualState.Resting,
            "在线空闲时，阿拉斯加必须进入休息状态");
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: false, hasActiveTask: true)
                == OperatorAssistantVisualState.OfflineSleeping,
            "Worker 掉线时，阿拉斯加必须进入睡眠状态");
    }

    private static void VerifyClosedWidgetCatalog()
    {
        var widgets = OperatorWidgetCatalog.CreateDefault();
        SmokeAssert.True(
            widgets.Select(widget => widget.Id).SequenceEqual(ExpectedWidgetIds),
            "默认工作组件目录必须保持固定顺序和闭集");
        SmokeAssert.True(
            widgets.Select(widget => widget.Id).Distinct(StringComparer.Ordinal).Count() == widgets.Count,
            "工作组件 ID 不得重复");

        var search = widgets.Single(widget => widget.Id == "search-insight");
        SmokeAssert.True(!search.IsAvailable, "Search 在有界外部采集接入前必须保持禁用");
        SmokeAssert.True(search.AvailabilityText == "尚未接入", "Search 禁用状态必须明确显示尚未接入");

        var forbiddenNames = new[]
        {
            "Provider", "Endpoint", "ApiKey", "Model", "Prompt", "Workflow",
            "Command", "Sql", "Assembly", "Script", "Executable",
        };
        var exposedNames = typeof(OperatorWidgetDescriptor)
            .GetProperties(BindingFlags.Public | BindingFlags.Instance)
            .Select(property => property.Name)
            .Concat(typeof(OperatorWidgetLayout).GetProperties(BindingFlags.Public | BindingFlags.Instance)
                .Select(property => property.Name))
            .ToArray();
        foreach (var forbidden in forbiddenNames)
        {
            SmokeAssert.True(
                !exposedNames.Any(name => name.Contains(forbidden, StringComparison.OrdinalIgnoreCase)),
                $"工作组件配置暴露禁止字段 {forbidden}");
        }
    }

    private static void VerifyLayoutNormalization()
    {
        var layout = OperatorWidgetLayout.Normalize(new[]
        {
            "video-creation",       // 合法 ID：必须保留用户顺序。
            "unknown-widget",       // 未知 ID：必须 fail closed 丢弃。
            "video-creation",       // 重复 ID：必须去重。
            "search-insight",       // 合法但当前不可执行：允许显示占位。
        });

        SmokeAssert.True(layout.WidgetIds.Count == ExpectedWidgetIds.Length, "规范化后必须补齐固定目录组件");
        SmokeAssert.True(layout.WidgetIds[0] == "video-creation", "合法用户排序必须被保留");
        SmokeAssert.True(layout.WidgetIds[1] == "search-insight", "第二个合法用户排序必须被保留");
        SmokeAssert.True(!layout.WidgetIds.Contains("unknown-widget", StringComparer.Ordinal), "未知组件不得进入布局");
        SmokeAssert.True(layout.WidgetIds.Distinct(StringComparer.Ordinal).Count() == layout.WidgetIds.Count, "布局不得含重复组件");
    }

    private static void VerifyProductizedWpfSurfaces()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var home = new OperatorHomePage();
                SmokeAssert.True(home.FindName("HeroNewTaskCard") is FrameworkElement, "首页缺少产品化新建任务 Hero");
                SmokeAssert.True(home.FindName("WidgetBoard") is FrameworkElement, "首页缺少可扩展工作组件区");

                var review = new OperatorReviewPage();
                SmokeAssert.True(review.FindName("ReviewSurface") is FrameworkElement, "待我审核页缺少产品化表面");

                var taskList = new OperatorTaskListPage();
                SmokeAssert.True(taskList.FindName("TaskListSurface") is FrameworkElement, "任务列表页缺少产品化表面");

                var wizard = new NewTaskWizardWindow(NewTaskWizardViewModel.CreateForSmokeTest());
                SmokeAssert.True(wizard.FindName("WizardSurface") is FrameworkElement, "新建任务向导缺少产品化表面");
                wizard.Close();

                var mascot = new AlaskanAssistantMascot();
                mascot.Measure(new Size(260, 300));
                mascot.Arrange(new Rect(0, 0, 260, 300));
                mascot.UpdateLayout();
                SmokeAssert.True(mascot.IsMeasureValid && mascot.IsArrangeValid, "阿拉斯加助手控件布局失败");
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
}
