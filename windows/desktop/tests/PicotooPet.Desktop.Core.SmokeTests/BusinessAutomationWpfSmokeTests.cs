using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>真实 STA WPF 冻结业务自动化页布局、纵向滚动、只读事实绑定和固定安全动作。</summary>
internal static class BusinessAutomationWpfSmokeTests
{
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
        var package = new BusinessWorkPackageRecord(
            WorkPackageId: "00000000-0000-4000-8000-000000000018",
            IdempotencyKey: "business-layout",
            ProducerId: "amazon-review-analyzer",
            ProducerVersion: "1.0.0",
            ProjectKey: "pet-dryer-us",
            AnalysisProfile: "reviews.voice_of_customer.v1",
            Objective: "Find supported customer pain points.",
            Status: "Completed",
            SourceDigest: new string('a', 64),
            CompressedSizeBytes: 1024,
            UncompressedSizeBytes: 2048,
            PackageObjectRelpath: null,
            PreprocessDigest: new string('b', 64),
            ResultPackageId: "00000000-0000-4000-8000-000000000019",
            DeepAiHandoffId: null,
            FailureCode: null,
            ErrorMessage: null,
            CreatedAt: now,
            UpdatedAt: now,
            FinishedAt: now);
        var viewModel = BusinessAutomationPageViewModel.CreateForSmokeTest(
            new[] { package },
            "local.intelligence.v1 · healthy · mac-worker");
        var page = new BusinessAutomationPage { DataContext = viewModel };

        page.Measure(new Size(1100, 800));
        page.Arrange(new Rect(0, 0, 1100, 800));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        page.UpdateLayout();

        SmokeAssert.True(page.IsMeasureValid, "Business Automation Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Business Automation Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0 && page.ActualHeight > 0, "Business Automation Page 布局尺寸无效");
        SmokeAssert.True(viewModel.CanDeliverResult, "Completed Result 应允许固定 Outbox 投递动作");
        SmokeAssert.True(!viewModel.CanCancel, "Completed Work Package 不允许取消");
        SmokeAssert.True(!viewModel.CanExportDeepAiHandoff, "没有 Handoff 的 Work Package 不允许导出");

        var pageScrollViewer = page.FindName("PageScrollViewer") as ScrollViewer;
        SmokeAssert.True(pageScrollViewer is not null, "Business Automation Page 必须提供页面级纵向 ScrollViewer");
        SmokeAssert.True(
            pageScrollViewer!.VerticalScrollBarVisibility == ScrollBarVisibility.Auto,
            "Business Automation Page 页面级纵向滚动条必须按内容自动显示");
        SmokeAssert.True(
            pageScrollViewer.HorizontalScrollBarVisibility == ScrollBarVisibility.Disabled,
            "Business Automation Page 不应依赖横向页面滚动");
        SmokeAssert.True(
            pageScrollViewer.ScrollableHeight > 0,
            "1100x800 真实视口下业务自动化累计面板必须产生可滚动纵向范围");

        var beforeOffset = pageScrollViewer.VerticalOffset;
        pageScrollViewer.ScrollToVerticalOffset(Math.Min(240, pageScrollViewer.ScrollableHeight));
        page.UpdateLayout();
        SmokeAssert.True(
            pageScrollViewer.VerticalOffset > beforeOffset,
            "业务自动化页必须能从顶部向下滚动到 Evaluation / Shadow / Promotion 区域");

        var dataGrid = FindDescendant<DataGrid>(page);
        SmokeAssert.True(dataGrid is not null, "Business Automation Page 缺少 DataGrid");
        var statusColumn = dataGrid!.Columns
            .OfType<DataGridBoundColumn>()
            .First(column => string.Equals(column.Header?.ToString(), "状态", StringComparison.Ordinal));
        SmokeAssert.True(
            statusColumn.Binding is Binding { Mode: BindingMode.OneWay },
            "业务状态必须显式 OneWay 绑定，不能让 WPF 尝试回写只读 record");
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
