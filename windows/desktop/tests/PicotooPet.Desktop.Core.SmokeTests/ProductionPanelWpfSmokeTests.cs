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

/// <summary>真实 STA WPF 冻结 Production panel 布局与 renderer 权限边界。</summary>
internal static class ProductionPanelWpfSmokeTests
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
        var source = new ProductionEligibleCreativeRecord(
            "00000000-0000-4000-8000-000000000020",
            "00000000-0000-4000-8000-000000000019",
            "pet-dryer-us",
            new string('a', 64),
            DateTimeOffset.UtcNow);
        using var viewModel = ProductionPanelViewModel.CreateForSmokeTest(new[] { source });
        var panel = new ProductionPanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 760));
        panel.Arrange(new Rect(0, 0, 1100, 760));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "ProductionPanel Measure 未完成");
        SmokeAssert.True(panel.IsArrangeValid, "ProductionPanel Arrange 未完成");
        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "ProductionPanel 布局尺寸无效");
        SmokeAssert.True(viewModel.CanCreate, "eligible Creative Package 应允许创建固定 Production Job");
        SmokeAssert.True(viewModel.CanPreflight, "ProductionPanel 应允许只读本机 Preflight");
        SmokeAssert.True(!viewModel.CanStart, "没有 Planned Job 时不得启动 ComfyUI render");
        SmokeAssert.True(!viewModel.CanCancel, "没有活动 Job 时不得取消");
        SmokeAssert.True(
            ProductionPanelViewModel.RendererText.Contains("127.0.0.1:8188", StringComparison.Ordinal),
            "ProductionPanel 必须明确固定 loopback renderer");

        var packageGrid = FindDescendants<DataGrid>(panel).FirstOrDefault();
        SmokeAssert.True(packageGrid is not null, "ProductionPanel 缺少 Creative Package DataGrid");
        var projectColumn = packageGrid!.Columns
            .OfType<DataGridBoundColumn>()
            .First(column => string.Equals(column.Header?.ToString(), "项目", StringComparison.Ordinal));
        SmokeAssert.True(
            projectColumn.Binding is Binding { Mode: BindingMode.OneWay },
            "Production eligible facts 必须显式 OneWay 绑定");

        var allText = string.Join(
            "\n",
            FindDescendants<TextBlock>(panel).Select(text => text.Text));
        SmokeAssert.True(
            allText.Contains("不接受 Workflow JSON", StringComparison.Ordinal),
            "ProductionPanel 必须显示 closed renderer 权限边界");
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
