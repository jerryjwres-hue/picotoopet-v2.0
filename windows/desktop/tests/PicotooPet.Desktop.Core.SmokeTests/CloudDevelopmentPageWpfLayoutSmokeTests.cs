using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Handoff、Provider、Return、Publication 与 Mock Broker 使用有界原生 WPF 控件并完成真实布局。</summary>
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

        page.Measure(new Size(1100, 1900));
        page.Arrange(new Rect(0, 0, 1100, 1900));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        page.Measure(new Size(1100, 1900));
        page.Arrange(new Rect(0, 0, 1100, 1900));
        page.UpdateLayout();

        SmokeAssert.True(page.IsMeasureValid, "Cloud Development Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Cloud Development Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Cloud Development Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Cloud Development Page 实际高度无效");
        var buttons = FindVisualChildren<Button>(page);
        SmokeAssert.True(
            buttons.Count >= 14,
            "页面必须提供 Handoff、Provider、Return、Publication 和 Broker 的原生操作按钮");
        SmokeAssert.True(
            buttons.Any(button => Equals(button.Content, "准备 Push + Draft PR")),
            "Phase 10E 必须在真实 WPF 树中提供受控 Publication 准备按钮");
        SmokeAssert.True(
            FindVisualChildren<TextBox>(page).Count >= 2,
            "Handoff 必须保留标题和目标摘要输入框");
        SmokeAssert.Equal(
            1,
            FindVisualChildren<ProviderSessionPanel>(page).Count,
            "Phase 10D-A 必须提供唯一的原生真实 Codex Provider 面板");
        SmokeAssert.Equal(
            1,
            FindVisualChildren<ProviderReviewPanel>(page).Count,
            "Phase 10D/E 必须提供唯一的原生 Review/Commit/Publication 面板");
        SmokeAssert.Equal(
            1,
            FindVisualChildren<ReturnValidationPanel>(page).Count,
            "Return 必须提供唯一的原生验证面板");
        SmokeAssert.Equal(
            1,
            FindVisualChildren<BrokerSessionPanel>(page).Count,
            "Mock Dev Broker 必须提供唯一的原生面板");
        SmokeAssert.Equal(
            0,
            FindVisualChildren<PasswordBox>(page).Count,
            "云端开发页面不得收集 Provider、仓库、Return 或 Broker 凭据");
        SmokeAssert.Equal(
            0,
            FindVisualChildren<WebBrowser>(page).Count,
            "云端开发页面不得使用浏览器 UI 或抓取 Usage 页面");
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
