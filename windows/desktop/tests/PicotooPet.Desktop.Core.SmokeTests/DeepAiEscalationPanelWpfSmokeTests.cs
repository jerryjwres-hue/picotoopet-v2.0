using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>真实 STA WPF 冻结 Paid-AI 面板布局、OneWay 事实绑定和无执行配置边界。</summary>
internal static class DeepAiEscalationPanelWpfSmokeTests
{
    private static readonly string[] ForbiddenPropertyFragments =
    [
        "Endpoint",
        "ApiKey",
        "ProviderKey",
        "Prompt",
        "Temperature",
        "Tools",
        "Command",
        "Shell",
        "Path",
        "Workflow",
    ];

    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunOnStaThread();
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

    private static void RunOnStaThread()
    {
        var job = new DeepAiEscalationRecord(
            "00000000-0000-4000-8000-000000000032",
            "business.local_intelligence",
            "00000000-0000-4000-8000-000000000031",
            new string('b', 64),
            "deep-ai.escalation.v1",
            "deep-ai/requests/request.json",
            new string('a', 64),
            "deep-ai.sanitizer.v1",
            "paid.reasoning.v1",
            new string('c', 64),
            "gpt-5.6-terra",
            12000,
            4000,
            2,
            0.50m,
            "WaitingApproval",
            "approval-001",
            new string('d', 64),
            DateTimeOffset.UtcNow.AddHours(1),
            null,
            null,
            null,
            null,
            null,
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow,
            null);
        var readiness = new DeepAiReadinessRecord(
            job.EscalationJobId,
            false,
            false,
            "DEEP_AI_EXECUTION_DISABLED",
            "handoff-001");
        var usage = new DeepAiUsageRecord(job.EscalationJobId, 0, 0, 0, 0m);
        var viewModel = DeepAiEscalationPanelViewModel.CreateForSmokeTest(
            [job],
            readiness,
            usage);
        var panel = new DeepAiEscalationPanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 720));
        panel.Arrange(new Rect(0, 0, 1100, 720));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "DeepAiEscalationPanel Measure 未完成。");
        SmokeAssert.True(panel.IsArrangeValid, "DeepAiEscalationPanel Arrange 未完成。");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Deep-AI panel 布局尺寸无效。");
        SmokeAssert.True(
            viewModel.ExecutionReadinessText.Contains("执行未启用", StringComparison.Ordinal),
            "Deep-AI 默认 readiness 必须一等显示‘执行未启用’。");
        SmokeAssert.True(
            viewModel.BudgetText.Contains("$0.50", StringComparison.Ordinal),
            "Deep-AI 面板必须显示冻结总预算上限。");
        SmokeAssert.True(
            !FindDescendants<TextBox>(panel).Any(),
            "Deep-AI 面板不得提供自由文本执行配置输入。");
        SmokeAssert.True(
            !FindDescendants<ComboBox>(panel).Any(),
            "Deep-AI 面板不得提供 provider/model 选择器。");

        var grid = FindDescendants<DataGrid>(panel).FirstOrDefault();
        SmokeAssert.True(grid is not null, "Deep-AI panel 缺少 escalation DataGrid。");
        var statusColumn = grid!.Columns
            .OfType<DataGridBoundColumn>()
            .First(column => string.Equals(column.Header?.ToString(), "状态", StringComparison.Ordinal));
        SmokeAssert.True(
            statusColumn.Binding is Binding { Mode: BindingMode.OneWay },
            "Deep-AI 状态必须显式 OneWay 绑定。");

        var allText = string.Join("\n", FindDescendants<TextBlock>(panel).Select(item => item.Text));
        SmokeAssert.True(
            allText.Contains("批准不等于自动花钱", StringComparison.Ordinal),
            "Deep-AI 面板必须显示 approval/spend 边界。");
        SmokeAssert.True(
            allText.Contains("不会自动提高预算", StringComparison.Ordinal),
            "Deep-AI 面板必须显示固定预算边界。");

        var propertyNames = typeof(DeepAiEscalationPanelViewModel)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        foreach (var fragment in ForbiddenPropertyFragments)
        {
            SmokeAssert.True(
                !propertyNames.Any(name => name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
                $"Deep-AI ViewModel 暴露禁止执行配置属性：{fragment}");
        }
    }

    private static IEnumerable<T> FindDescendants<T>(DependencyObject root) where T : DependencyObject
    {
        var count = System.Windows.Media.VisualTreeHelper.GetChildrenCount(root);
        for (var index = 0; index < count; index++)
        {
            var child = System.Windows.Media.VisualTreeHelper.GetChild(root, index);
            if (child is T typed)
            {
                yield return typed;
            }
            foreach (var descendant in FindDescendants<T>(child))
            {
                yield return descendant;
            }
        }
    }
}
