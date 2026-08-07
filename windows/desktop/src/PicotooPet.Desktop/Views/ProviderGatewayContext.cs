using System.Windows;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>通过可继承 Attached Property 向独立 Codex Provider 面板提供受限网关。</summary>
public static class ProviderGatewayContext
{
    public static readonly DependencyProperty GatewayProperty =
        DependencyProperty.RegisterAttached(
            "Gateway",
            typeof(IProviderSessionGateway),
            typeof(ProviderGatewayContext),
            new FrameworkPropertyMetadata(
                defaultValue: null,
                FrameworkPropertyMetadataOptions.Inherits));

    public static void SetGateway(DependencyObject target, IProviderSessionGateway? value)
    {
        ArgumentNullException.ThrowIfNull(target);
        target.SetValue(GatewayProperty, value);
    }

    public static IProviderSessionGateway? GetGateway(DependencyObject target)
    {
        ArgumentNullException.ThrowIfNull(target);
        return (IProviderSessionGateway?)target.GetValue(GatewayProperty);
    }
}
