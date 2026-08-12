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

/// <summary>真实 STA WPF 冻结质量评估布局、OneWay 事实绑定和零策略执行权限。</summary>
internal static class QualityEvaluationPanelWpfSmokeTests
{
    private static readonly string[] ForbiddenPropertyFragments =
    [
        "Prompt",
        "Endpoint",
        "ApiKey",
        "ProviderKey",
        "ModelSelector",
        "Budget",
        "Formula",
        "Sql",
        "Workflow",
        "Command",
        "Shell",
        "Path",
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
        var snapshot = new QualityEvaluationSnapshotRecord(
            "00000000-0000-4000-8000-000000000041",
            "pet-dryer-us",
            "quality.offline.v1",
            null,
            null,
            null,
            10000,
            new string('a', 64),
            new string('b', 64),
            10,
            DateTimeOffset.UtcNow);
        var run = new QualityEvaluationRunRecord(
            "00000000-0000-4000-8000-000000000042",
            snapshot.SnapshotId,
            "quality.offline.v1",
            "quality.offline.v1",
            "Completed",
            new string('c', 64),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var metric = new QualityEvaluationMetricRecord(
            "metric-001",
            run.EvaluationRunId,
            "human_rejected_or_modified_rate",
            0.4,
            2,
            5,
            "available",
            "stage_profile",
            "reviews.voice_of_customer.v1",
            new string('d', 64));
        var candidate = new QualityImprovementCandidateRecord(
            "00000000-0000-4000-8000-000000000043",
            "pet-dryer-us",
            run.EvaluationRunId,
            snapshot.SnapshotId,
            "quality.offline.v1",
            "PROMPT_REVIEW",
            "stage_profile",
            "reviews.voice_of_customer.v1",
            new string('e', 64),
            ["HUMAN_REJECTED_OR_MODIFIED_RATE_HIGH"],
            "Prepared",
            new string('f', 64),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var viewModel = QualityEvaluationPanelViewModel.CreateForSmokeTest(
            snapshot,
            run,
            [metric],
            [candidate]);
        var panel = new QualityEvaluationPanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 720));
        panel.Arrange(new Rect(0, 0, 1100, 720));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "QualityEvaluationPanel Measure 未完成。");
        SmokeAssert.True(panel.IsArrangeValid, "QualityEvaluationPanel Arrange 未完成。");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "质量评估 panel 布局尺寸无效。");
        SmokeAssert.True(
            viewModel.ProjectText.Contains("pet-dryer-us", StringComparison.Ordinal),
            "质量评估必须显示冻结 project scope。");
        SmokeAssert.True(
            viewModel.SnapshotText.Contains("10", StringComparison.Ordinal),
            "质量评估必须显示 snapshot member count。");

        // Input authority gate      23.1 面板不得提供自由策略、公式或执行配置输入。
        SmokeAssert.True(!FindDescendants<TextBox>(panel).Any(), "质量评估面板不得提供自由文本策略输入。");
        SmokeAssert.True(!FindDescendants<ComboBox>(panel).Any(), "质量评估面板不得提供模型/provider 选择器。");

        var grids = FindDescendants<DataGrid>(panel).ToArray();
        SmokeAssert.True(grids.Length >= 2, "质量评估面板必须显示 metrics 与 candidates DataGrid。");
        foreach (var grid in grids)
        {
            foreach (var column in grid.Columns.OfType<DataGridBoundColumn>())
            {
                SmokeAssert.True(
                    column.Binding is Binding { Mode: BindingMode.OneWay },
                    $"质量评估只读列必须显式 OneWay：{column.Header}");
            }
        }

        var allText = string.Join("\n", FindDescendants<TextBlock>(panel).Select(item => item.Text));
        SmokeAssert.True(
            allText.Contains("不会自动修改", StringComparison.Ordinal),
            "质量评估面板必须显示零自动策略变更边界。");
        SmokeAssert.True(
            allText.Contains("AcceptedForShadow", StringComparison.Ordinal),
            "质量评估面板必须解释 AcceptedForShadow 仅为审阅事实。");

        var propertyNames = typeof(QualityEvaluationPanelViewModel)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        foreach (var fragment in ForbiddenPropertyFragments)
        {
            SmokeAssert.True(
                !propertyNames.Any(name => name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
                $"质量评估 ViewModel 暴露禁止策略/执行属性：{fragment}");
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
