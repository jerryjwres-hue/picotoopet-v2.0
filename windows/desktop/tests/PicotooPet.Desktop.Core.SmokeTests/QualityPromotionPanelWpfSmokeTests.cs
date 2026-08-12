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

/// <summary>真实 STA WPF 冻结 25.1 Promotion 布局、OneWay 事实绑定和闭合 rollback 选择器。</summary>
internal static class QualityPromotionPanelWpfSmokeTests
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
        "PathInput",
        "Threshold",
        "Patch",
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
        var shadow = new QualityShadowRunRecord(
            "00000000-0000-4000-8000-000000000061",
            "candidate-001",
            "evaluation-001",
            "snapshot-001",
            "pet-dryer-us",
            "PROMPT_REVIEW",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "quality.shadow.v1",
            "quality.shadow.split.v1",
            "Completed",
            "Supported",
            new string('4', 64),
            new string('5', 64),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow);
        var promotion = new QualityPromotionRecord(
            "00000000-0000-4000-8000-000000000062",
            shadow.ShadowRunId,
            shadow.CandidateId,
            shadow.ProjectKey,
            shadow.CandidateClass,
            shadow.CandidateDigest,
            shadow.ReportDigest,
            shadow.EvaluationReportDigest,
            shadow.SnapshotDigest,
            "quality.promotion.v1",
            new string('6', 64),
            1,
            new string('7', 64),
            "AwaitingApproval",
            null,
            DateTimeOffset.UtcNow,
            null,
            null);
        var activation = new QualityPromotionApprovalRequestRecord(
            "approval-001",
            promotion.PromotionId,
            "PromotionActivation",
            new string('8', 64),
            "Pending",
            null,
            null,
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow.AddMinutes(30),
            null);
        var history = new QualityPromotionHistoryRecord(
            Array.Empty<QualityPromotionDecisionRecord>(),
            Array.Empty<QualityPromotionRollbackRecord>());
        var viewModel = QualityPromotionPanelViewModel.CreateForSmokeTest(
            [shadow],
            [promotion],
            activation,
            null,
            history);
        var panel = new QualityPromotionPanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 780));
        panel.Arrange(new Rect(0, 0, 1100, 780));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "QualityPromotionPanel Measure 未完成。");
        SmokeAssert.True(panel.IsArrangeValid, "QualityPromotionPanel Arrange 未完成。");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Promotion panel 布局尺寸无效。");
        SmokeAssert.True(viewModel.CanDecideActivation, "AwaitingApproval + Pending exact request 应允许闭合决定。");
        SmokeAssert.True(viewModel.RollbackReasons.SequenceEqual(
            ["RegressionObserved", "UnexpectedImpact", "OperatorDecision"]),
            "Rollback reason 必须保持三值闭合枚举。");

        // Input authority gate      唯一 ComboBox 只允许固定 rollback reason；禁止自由文本策略输入。
        SmokeAssert.True(!FindDescendants<TextBox>(panel).Any(), "Promotion 面板不得提供自由文本策略输入。");
        var comboBoxes = FindDescendants<ComboBox>(panel).ToArray();
        SmokeAssert.True(comboBoxes.Length == 1, "Promotion 面板只能有一个固定 rollback reason 选择器。");

        var grids = FindDescendants<DataGrid>(panel).ToArray();
        SmokeAssert.True(grids.Length >= 3, "Promotion 面板必须显示 Shadow、Promotion 和决策历史事实表。");
        foreach (var grid in grids)
        {
            foreach (var column in grid.Columns.OfType<DataGridBoundColumn>())
            {
                SmokeAssert.True(
                    column.Binding is Binding { Mode: BindingMode.OneWay },
                    $"Promotion 只读列必须显式 OneWay：{column.Header}");
            }
        }

        var allText = string.Join("\n", FindDescendants<TextBlock>(panel).Select(item => item.Text));
        SmokeAssert.True(allText.Contains("exact request digest", StringComparison.Ordinal), "Promotion 面板必须显示 exact approval 边界。");
        SmokeAssert.True(allText.Contains("不会被 runtime 读取", StringComparison.Ordinal), "Promotion 面板必须显示 governance-only 边界。");

        var propertyNames = typeof(QualityPromotionPanelViewModel)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        foreach (var fragment in ForbiddenPropertyFragments)
        {
            SmokeAssert.True(
                !propertyNames.Any(name => name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
                $"Promotion ViewModel 暴露禁止策略/执行属性：{fragment}");
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
