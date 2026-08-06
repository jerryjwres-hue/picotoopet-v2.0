using System.Windows;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>通过可继承 Attached Property 向独立 Broker 面板提供受限网关。</summary>
public static class BrokerGatewayContext
{
    /// <summary>在当前视觉树中继承的 Broker Session 网关。</summary>
    public static readonly DependencyProperty GatewayProperty =
        DependencyProperty.RegisterAttached(
            "Gateway",
            typeof(IBrokerSessionGateway),
            typeof(BrokerGatewayContext),
            new FrameworkPropertyMetadata(
                defaultValue: null,
                FrameworkPropertyMetadataOptions.Inherits));

    public static void SetGateway(DependencyObject target, IBrokerSessionGateway? value)
    {
        ArgumentNullException.ThrowIfNull(target);
        target.SetValue(GatewayProperty, value);
    }

    public static IBrokerSessionGateway? GetGateway(DependencyObject target)
    {
        ArgumentNullException.ThrowIfNull(target);
        return (IBrokerSessionGateway?)target.GetValue(GatewayProperty);
    }
}
