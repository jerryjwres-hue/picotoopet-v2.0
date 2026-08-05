using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Phase 10A 与 10B-A 使用有界原生 WPF 控件并完成真实布局。</summary>
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

        page.Measure(new Size(1100, 980));
        page.Arrange(new Rect(0, 0, 1100, 980));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(page.IsMeasureValid, "Cloud Development Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Cloud Development Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Cloud Development Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Cloud Development Page 实际高度无效");
        SmokeAssert.True(
            FindVisualChildren<Button>(page).Count >= 5,
            "页面必须提供 Handoff 刷新/准备/审批和 Return 刷新/演练按钮");
        SmokeAssert.True(
            FindVisualChildren<TextBox>(page).Count >= 2,
            "Phase 10A 必须保留标题和目标摘要输入框");
        SmokeAssert.Equal(
            1,
            FindVisualChildren<ReturnValidationPanel>(page).Count,
            "Phase 10B-A 必须提供唯一的原生 Return 验证面板");
        SmokeAssert.Equal(
            0,
            FindVisualChildren<PasswordBox>(page).Count,
            "云端开发页面不得收集 Provider、仓库或 Return 凭据");
        SmokeAssert.Equal(
            0,
            FindVisualChildren<WebBrowser>(page).Count,
            "云端开发页面不得使用浏览器 UI");
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
