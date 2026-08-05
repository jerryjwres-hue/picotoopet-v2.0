using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证云端开发合同页是可布局、无执行动作的原生 WPF 页面。</summary>
internal static class CloudDevelopmentPageWpfLayoutSmokeTests
{
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunLayout();
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

    private static void RunLayout()
    {
        var page = new CloudDevelopmentPage
        {
            DataContext = new CloudDevelopmentPageViewModel(),
        };

        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(page.IsMeasureValid, "Cloud Development Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Cloud Development Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Cloud Development Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Cloud Development Page 实际高度无效");
        SmokeAssert.Equal(
            0,
            FindVisualChildren<Button>(page).Count,
            "合同状态页不得包含执行按钮");
    }

    private static IReadOnlyList<T> FindVisualChildren<T>(DependencyObject root)
        where T : DependencyObject
    {
        var matches = new List<T>();
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                matches.Add(match);
            }
            matches.AddRange(FindVisualChildren<T>(child));
        }
        return matches;
    }
}
