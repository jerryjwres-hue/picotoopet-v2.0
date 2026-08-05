using System.Windows;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>通过 WPF 属性继承显式传递受限 Return 网关，避免全局 Service Locator。</summary>
public static class ReturnGatewayContext
{
    public static readonly DependencyProperty GatewayProperty =
        DependencyProperty.RegisterAttached(
            "Gateway",
            typeof(IReturnGateway),
            typeof(ReturnGatewayContext),
            new FrameworkPropertyMetadata(
                defaultValue: null,
                FrameworkPropertyMetadataOptions.Inherits));

    /// <summary>把组合根创建的受限 Return 网关附加到 Shell 视觉树。</summary>
    public static void SetGateway(DependencyObject element, IReturnGateway? value)
    {
        ArgumentNullException.ThrowIfNull(element);
        element.SetValue(GatewayProperty, value);
    }

    /// <summary>从当前 WPF 视觉树读取继承的受限 Return 网关。</summary>
    public static IReturnGateway? GetGateway(DependencyObject element)
    {
        ArgumentNullException.ThrowIfNull(element);
        return (IReturnGateway?)element.GetValue(GatewayProperty);
    }
}
