using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using PicotooPet.Desktop.Services;
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

    private static readonly string[] ForbiddenWidgetPropertyNames =
    {
        "Provider",                // 禁止任意 Provider 注入。
        "ProviderId",              // 禁止任意 Provider 标识注入。
        "ProviderKey",             // 禁止 Windows 保存 Provider 密钥。
        "Endpoint",                // 禁止任意 Endpoint 注入。
        "EndpointUrl",             // 禁止任意 Endpoint URL 注入。
        "ApiKey",                  // 禁止 Windows 保存 API Key。
        "Model",                   // 禁止任意模型选择。
        "ModelId",                 // 禁止任意模型标识选择。
        "Prompt",                  // 禁止任意 Prompt 注入。
        "PromptTemplate",          // 禁止任意 Prompt 模板注入。
        "Workflow",                // 禁止任意工作流注入。
        "WorkflowId",              // 禁止任意工作流标识注入。
        "Command",                 // 禁止任意命令执行。
        "CommandLine",             // 禁止任意命令行执行。
        "Sql",                     // 禁止任意 SQL 执行。
        "SqlText",                 // 禁止任意 SQL 文本执行。
        "Assembly",                // 禁止任意程序集加载。
        "AssemblyPath",            // 禁止任意程序集路径加载。
        "Script",                  // 禁止任意脚本加载。
        "ScriptPath",              // 禁止任意脚本路径加载。
        "Executable",              // 禁止任意可执行文件入口。
        "ExecutablePath",          // 禁止任意可执行文件路径入口。
    };

    private static readonly string[] LayoutOrderFixture =
    {
        "video-creation",          // 合法 ID：必须保留用户顺序。
        "unknown-widget",          // 未知 ID：必须 fail closed 丢弃。
        "video-creation",          // 重复 ID：必须去重。
        "search-insight",          // 合法但当前不可执行：允许显示占位。
    };

    private static readonly string[] StoredOrderFixture =
    {
        "video-creation",          // 保存时验证合法排序恢复。
        "search-insight",          // Search 可显示，但仍保持不可执行。
    };

    private static readonly string[] StoredHiddenFixture =
    {
        "comment-analysis",        // 验证固定组件的隐藏偏好可恢复。
    };

    public static void Run()
    {
        VerifyAssistantStateResolver();
        VerifyClosedWidgetCatalog();
        VerifyLayoutNormalization();
        VerifyWidgetLayoutStore();
        VerifyProductizedWpfSurfaces();
    }

    private static void VerifyAssistantStateResolver()
    {
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: true, hasRealExecution: true)
                == OperatorAssistantVisualState.Working,
            "只有真实执行信号存在时，阿拉斯加才可以进入工作状态");
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: true, hasRealExecution: false)
                == OperatorAssistantVisualState.Resting,
            "仅连接正常但没有真实执行时，阿拉斯加必须进入休息状态");
        SmokeAssert.True(
            OperatorAssistantStateResolver.Resolve(coreOnline: true, workerOnline: false, hasRealExecution: true)
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

        var exposedNames = typeof(OperatorWidgetDescriptor)
            .GetProperties(BindingFlags.Public | BindingFlags.Instance)
            .Select(property => property.Name)
            .Concat(typeof(OperatorWidgetLayout).GetProperties(BindingFlags.Public | BindingFlags.Instance)
                .Select(property => property.Name))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var forbidden in ForbiddenWidgetPropertyNames)
        {
            SmokeAssert.True(
                !exposedNames.Contains(forbidden),
                $"工作组件配置暴露禁止字段 {forbidden}");
        }
    }

    private static void VerifyLayoutNormalization()
    {
        var layout = OperatorWidgetLayout.Normalize(LayoutOrderFixture);

        SmokeAssert.True(layout.WidgetIds.Count == ExpectedWidgetIds.Length, "规范化后必须补齐固定目录组件");
        SmokeAssert.True(layout.WidgetIds[0] == "video-creation", "合法用户排序必须被保留");
        SmokeAssert.True(layout.WidgetIds[1] == "search-insight", "第二个合法用户排序必须被保留");
        SmokeAssert.True(!layout.WidgetIds.Contains("unknown-widget", StringComparer.Ordinal), "未知组件不得进入布局");
        SmokeAssert.True(layout.WidgetIds.Distinct(StringComparer.Ordinal).Count() == layout.WidgetIds.Count, "布局不得含重复组件");
    }

    private static void VerifyWidgetLayoutStore()
    {
        var root = Path.Combine(Path.GetTempPath(), $"picotoopet-widget-layout-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        var path  = Path.Combine(root, "operator-widgets.json");
        var store = new OperatorWidgetLayoutStore(path);

        try
        {
            var requested = OperatorWidgetLayout.Normalize(StoredOrderFixture, StoredHiddenFixture);
            SmokeAssert.True(store.TrySave(requested), "工作组件布局必须可以原子保存");

            var loaded = store.LoadOrDefault();
            SmokeAssert.True(loaded.WidgetIds[0] == "video-creation", "已保存的合法组件顺序必须恢复");
            SmokeAssert.True(loaded.HiddenWidgetIds.SequenceEqual(StoredHiddenFixture), "已保存显隐偏好必须恢复");

            File.WriteAllText(path, "{not-valid-json");
            var fallback = store.LoadOrDefault();
            SmokeAssert.True(
                fallback.WidgetIds.SequenceEqual(ExpectedWidgetIds),
                "损坏组件布局必须安全回退固定默认目录");
            SmokeAssert.True(fallback.HiddenWidgetIds.Count == 0, "损坏组件布局不得残留隐藏状态");
        }
        finally
        {
            try
            {
                Directory.Delete(root, recursive: true);
            }
            catch (IOException)
            {
                // Windows CI 若文件句柄正在收尾，不让临时偏好清理影响产品行为断言。
            }
            catch (UnauthorizedAccessException)
            {
                // 临时测试目录权限异常不应掩盖组件布局合同本身的结果。
            }
        }
    }

    private static void VerifyProductizedWpfSurfaces()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var home = new OperatorHomePage();
                SmokeAssert.True(home.FindName("ReferenceHomeLayout") is FrameworkElement, "首页缺少参考图信息架构根布局");
                SmokeAssert.True(home.FindName("HeroNewTaskCard") is FrameworkElement, "首页缺少产品化新建任务 Hero");
                SmokeAssert.True(home.FindName("TaskSummaryBoard") is FrameworkElement, "首页缺少三桶任务摘要区");
                SmokeAssert.True(home.FindName("SystemStatusCard") is FrameworkElement, "首页缺少右侧系统状态卡");
                SmokeAssert.True(home.FindName("ResourceMonitorCard") is FrameworkElement, "首页缺少右侧资源监控位");
                SmokeAssert.True(home.FindName("RecentTasksPanel") is FrameworkElement, "首页缺少最近任务区");
                SmokeAssert.True(home.FindName("SystemActivityPanel") is FrameworkElement, "首页缺少系统动态区");
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
