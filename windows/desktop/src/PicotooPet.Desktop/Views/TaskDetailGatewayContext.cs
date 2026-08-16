using System.Windows;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>把单一 ControlCenterSession 的任务详情入口通过 WPF 继承属性下发到页面。</summary>
public static class TaskDetailGatewayContext
{
    public static readonly DependencyProperty GatewayProperty = DependencyProperty.RegisterAttached(
        "Gateway",
        typeof(ControlCenterTaskDetailGateway),
        typeof(TaskDetailGatewayContext),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.Inherits));

    public static void SetGateway(DependencyObject element, ControlCenterTaskDetailGateway gateway)
    {
        ArgumentNullException.ThrowIfNull(element);
        ArgumentNullException.ThrowIfNull(gateway);
        element.SetValue(GatewayProperty, gateway);
    }

    public static ControlCenterTaskDetailGateway? GetGateway(DependencyObject element)
    {
        ArgumentNullException.ThrowIfNull(element);
        return element.GetValue(GatewayProperty) as ControlCenterTaskDetailGateway;
    }
}
