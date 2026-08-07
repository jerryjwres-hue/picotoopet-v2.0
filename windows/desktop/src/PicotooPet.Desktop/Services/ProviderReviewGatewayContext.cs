using System.Windows;

namespace PicotooPet.Desktop.Services;

/// <summary>通过 WPF 继承附加属性向 Review 面板注入受控 gateway。</summary>
public static class ProviderReviewGatewayContext
{
    public static readonly DependencyProperty GatewayProperty =
        DependencyProperty.RegisterAttached(
            "Gateway",
            typeof(IProviderReviewGateway),
            typeof(ProviderReviewGatewayContext),
            new FrameworkPropertyMetadata(
                null,
                FrameworkPropertyMetadataOptions.Inherits));

    public static void SetGateway(DependencyObject element, IProviderReviewGateway? value)
    {
        ArgumentNullException.ThrowIfNull(element);
        element.SetValue(GatewayProperty, value);
    }

    public static IProviderReviewGateway? GetGateway(DependencyObject element)
    {
        ArgumentNullException.ThrowIfNull(element);
        return element.GetValue(GatewayProperty) as IProviderReviewGateway;
    }
}
