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

/// <summary>真实 STA WPF 冻结 2.3.21.1 Business Pipeline 内嵌控制面与只读状态绑定。</summary>
internal static class BusinessPipelinePanelWpfSmokeTests
{
    private static readonly string[] ExpectedAdapterProfiles =
    [
        "amazon.reviews_export.v1",
        "inspiration.ideas_export.v1",
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
        var now = DateTimeOffset.UtcNow;
        var run = new BusinessPipelineRunRecord(
            PipelineRunId: "00000000-0000-4000-8000-000000000022",
            WorkPackageId: "00000000-0000-4000-8000-000000000021",
            ResultPackageId: "00000000-0000-4000-8000-000000000023",
            CreativeJobId: "00000000-0000-4000-8000-000000000024",
            CreativePackageId: "00000000-0000-4000-8000-000000000025",
            ProductionJobId: "00000000-0000-4000-8000-000000000026",
            ProductionPackageId: "00000000-0000-4000-8000-000000000027",
            ReturnPackageId: "00000000-0000-4000-8000-000000000028",
            ProjectKey: "pet-dryer-us",
            ProducerId: "picotoopet.windows.amazon-adapter",
            ProducerVersion: "2.3.21.1",
            AdapterProfile: "amazon.reviews_export.v1",
            Status: "Completed",
            QualityOutcome: "PASS",
            FailureCode: null,
            ErrorMessage: null,
            IdempotencyKey: "pipeline-smoke-001",
            CreatedAt: now,
            UpdatedAt: now,
            FinishedAt: now);
        var viewModel = BusinessPipelinePanelViewModel.CreateForSmokeTest(new[] { run });
        SmokeAssert.True(!viewModel.CanSubmitSource, "没有来源文件时不应允许 Adapter 提交。");
        viewModel.SourcePath = @"C:\exports\reviews.csv";
        viewModel.ProjectKey = "pet-dryer-us";
        viewModel.Objective = "提取高置信 VOC 痛点并进入端到端生产。";
        SmokeAssert.True(viewModel.CanSubmitSource, "合法 source/project/objective 应允许 first-party Adapter 提交。");
        var panel = new BusinessPipelinePanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 560));
        panel.Arrange(new Rect(0, 0, 1100, 560));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "Business Pipeline Panel Measure 未完成");
        SmokeAssert.True(panel.IsArrangeValid, "Business Pipeline Panel Arrange 未完成");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Business Pipeline Panel 布局尺寸无效");
        SmokeAssert.True(viewModel.CanDownloadReturnPackage, "Completed pipeline 应允许下载 Return Package。");
        SmokeAssert.True(!viewModel.CanCancel, "Completed pipeline 不允许取消。");
        SmokeAssert.True(
            viewModel.AdapterProfiles.SequenceEqual(ExpectedAdapterProfiles),
            "Windows 控制面必须只暴露两个 first-party adapter profile。");

        var dataGrid = FindDescendant<DataGrid>(panel);
        SmokeAssert.True(dataGrid is not null, "Business Pipeline Panel 缺少 DataGrid");
        var statusColumn = dataGrid!.Columns
            .OfType<DataGridBoundColumn>()
            .First(column => string.Equals(column.Header?.ToString(), "状态", StringComparison.Ordinal));
        SmokeAssert.True(
            statusColumn.Binding is Binding { Mode: BindingMode.OneWay },
            "Pipeline 状态必须显式 OneWay，不能让 WPF 回写只读 record。");
    }

    private static T? FindDescendant<T>(DependencyObject root) where T : DependencyObject
    {
        var count = System.Windows.Media.VisualTreeHelper.GetChildrenCount(root);
        for (var index = 0; index < count; index++)
        {
            var child = System.Windows.Media.VisualTreeHelper.GetChild(root, index);
            if (child is T typed)
            {
                return typed;
            }
            var descendant = FindDescendant<T>(child);
            if (descendant is not null)
            {
                return descendant;
            }
        }
        return null;
    }
}
