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

/// <summary>真实 STA WPF 冻结 24.1 Shadow 布局、OneWay 事实绑定和零策略输入权限。</summary>
internal static class QualityShadowPanelWpfSmokeTests
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
        "Threshold",
        "Seed",
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
        var candidate = new QualityImprovementCandidateRecord(
            "00000000-0000-4000-8000-000000000051",
            "pet-dryer-us",
            "evaluation-001",
            "snapshot-001",
            "quality.offline.v1",
            "PROMPT_REVIEW",
            "stage_profile",
            "reviews.voice_of_customer.v1",
            new string('a', 64),
            ["HUMAN_REJECTED_OR_MODIFIED_RATE_HIGH"],
            "AcceptedForShadow",
            new string('b', 64),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var run = new QualityShadowRunRecord(
            "00000000-0000-4000-8000-000000000052",
            candidate.CandidateId,
            candidate.EvaluationRunId,
            candidate.SnapshotId,
            candidate.ProjectKey,
            candidate.CandidateClass,
            candidate.CandidateDigest,
            new string('c', 64),
            new string('d', 64),
            "quality.shadow.v1",
            "quality.shadow.split.v1",
            "Completed",
            "Supported",
            new string('e', 64),
            new string('f', 64),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var baseline = new QualityShadowArmMetricRecord(
            "metric-baseline",
            run.ShadowRunId,
            "baseline",
            "human_rejected_or_modified_rate",
            1.0,
            30,
            30,
            "available",
            new string('1', 64));
        var shadow = new QualityShadowArmMetricRecord(
            "metric-shadow",
            run.ShadowRunId,
            "shadow",
            "human_rejected_or_modified_rate",
            1.0,
            30,
            30,
            "available",
            new string('2', 64));
        var viewModel = QualityShadowPanelViewModel.CreateForSmokeTest(
            [candidate],
            run,
            [baseline, shadow]);
        var panel = new QualityShadowPanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 720));
        panel.Arrange(new Rect(0, 0, 1100, 720));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "QualityShadowPanel Measure 未完成。");
        SmokeAssert.True(panel.IsArrangeValid, "QualityShadowPanel Arrange 未完成。");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Shadow panel 布局尺寸无效。");
        SmokeAssert.True(viewModel.RunText.Contains("Supported", StringComparison.Ordinal), "Shadow 必须显示闭合 verdict。");
        SmokeAssert.True(viewModel.CanAcceptForPromotionReview, "Supported Shadow 应允许记录 Promotion Review fact。");

        // Input authority gate      24.1 面板不得出现自由 Prompt/Model/Provider/公式/阈值输入。
        SmokeAssert.True(!FindDescendants<TextBox>(panel).Any(), "Shadow 面板不得提供自由文本策略输入。");
        SmokeAssert.True(!FindDescendants<ComboBox>(panel).Any(), "Shadow 面板不得提供模型/provider 选择器。");

        var grids = FindDescendants<DataGrid>(panel).ToArray();
        SmokeAssert.True(grids.Length >= 2, "Shadow 面板必须显示 candidates 与 A/B metrics DataGrid。");
        foreach (var grid in grids)
        {
            foreach (var column in grid.Columns.OfType<DataGridBoundColumn>())
            {
                SmokeAssert.True(
                    column.Binding is Binding { Mode: BindingMode.OneWay },
                    $"Shadow 只读列必须显式 OneWay：{column.Header}");
            }
        }

        var allText = string.Join("\n", FindDescendants<TextBlock>(panel).Select(item => item.Text));
        SmokeAssert.True(allText.Contains("AcceptedForShadow", StringComparison.Ordinal), "Shadow 面板必须显示资格边界。");
        SmokeAssert.True(allText.Contains("不会自动 Promotion", StringComparison.Ordinal), "Shadow 面板必须显示零自动 Promotion 边界。");

        var propertyNames = typeof(QualityShadowPanelViewModel)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        foreach (var fragment in ForbiddenPropertyFragments)
        {
            SmokeAssert.True(
                !propertyNames.Any(name => name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
                $"Shadow ViewModel 暴露禁止策略/执行属性：{fragment}");
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
