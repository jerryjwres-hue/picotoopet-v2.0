using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>真实 STA 验证 Phase 10D-B Review 面板只读布局与数据绑定。</summary>
internal static class ProviderReviewPanelWpfLayoutSmokeTests
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
        var panel = new ProviderReviewPanel();
        SmokeAssert.True(panel.DataContext is ProviderReviewViewModel, "Review 面板必须具有确定性 smoke ViewModel");

        panel.Measure(new Size(1000, 1000));
        panel.Arrange(new Rect(0, 0, 1000, 1000));
        panel.UpdateLayout();
        panel.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        panel.Measure(new Size(1000, 1000));
        panel.Arrange(new Rect(0, 0, 1000, 1000));
        panel.UpdateLayout();

        SmokeAssert.True(panel.IsMeasureValid, "Provider Review Measure 未完成");
        SmokeAssert.True(panel.IsArrangeValid, "Provider Review Arrange 未完成");
        SmokeAssert.True(panel.ActualWidth > 0, "Provider Review 实际宽度无效");
        SmokeAssert.True(panel.ActualHeight > 0, "Provider Review 实际高度无效");

        var textBoxes = FindVisualChildren<TextBox>(panel);
        SmokeAssert.True(
            textBoxes.All(textBox => textBox.IsReadOnly),
            "Review 面板如使用 TextBox，只能用于只读 diff，不能编辑 patch");
        SmokeAssert.Equal(0, FindVisualChildren<PasswordBox>(panel).Count, "Review 面板不得收集凭据");
        SmokeAssert.Equal(0, FindVisualChildren<WebBrowser>(panel).Count, "Review 面板不得使用 WebView/浏览器");
        SmokeAssert.True(FindVisualChildren<Button>(panel).Count >= 3, "必须提供接受、拒绝和刷新候选固定按钮");
    }

    private static List<T> FindVisualChildren<T>(DependencyObject root)
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
