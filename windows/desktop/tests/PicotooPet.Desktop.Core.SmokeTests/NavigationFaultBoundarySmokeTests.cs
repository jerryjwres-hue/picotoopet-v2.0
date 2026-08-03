using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 WPF 布局流水线中验证页面故障边界可以隔离异常并恢复。</summary>
internal static class NavigationFaultBoundarySmokeTests
{
    /// <summary>强制子元素在 Measure 阶段抛错，再验证替换内容仍能完成布局。</summary>
    public static void Run()
    {
        Exception? observedException = null;
        var host = new NavigationContentHost
        {
            Content = new ThrowingMeasureElement(),
        };
        host.NavigationFaulted += (_, eventArgs) =>
            observedException = eventArgs.Exception;

        host.Measure(new Size(960, 680));
        host.Arrange(new Rect(0, 0, 960, 680));
        host.UpdateLayout();
        host.Dispatcher.Invoke(static () => { }, DispatcherPriority.ApplicationIdle);

        SmokeAssert.True(
            observedException is InvalidOperationException,
            "页面布局故障未被 NavigationContentHost 隔离");

        host.Content = new Border
        {
            Child = new TextBlock
            {
                Text = "安全回退页面",
            },
        };
        host.Measure(new Size(960, 680));
        host.Arrange(new Rect(0, 0, 960, 680));
        host.UpdateLayout();

        SmokeAssert.True(host.IsMeasureValid, "故障后的替换页面 Measure 未完成");
        SmokeAssert.True(host.IsArrangeValid, "故障后的替换页面 Arrange 未完成");
    }

    /// <summary>确定性复现页面模板或绑定在 Measure 阶段抛出的布局异常。</summary>
    private sealed class ThrowingMeasureElement : FrameworkElement
    {
        /// <summary>始终抛出可恢复异常，模拟单个页面的布局故障。</summary>
        protected override Size MeasureOverride(Size availableSize) =>
            throw new InvalidOperationException("navigation layout fixture");
    }
}
