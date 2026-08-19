using System.Windows;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows 只读查看 Coding Escalation 决策；不暴露 Provider 执行权限。</summary>
public interface ICodingEscalationDecisionGateway
{
    Task<CodingEscalationDecisionRecord> GetDecisionAsync(
        string goalId,
        CancellationToken cancellationToken);
}

/// <summary>用继承型 attached property 把只读 gateway 注入 Cloud Development 子面板。</summary>
public static class CodingEscalationDecisionGatewayContext
{
    public static readonly DependencyProperty GatewayProperty = DependencyProperty.RegisterAttached(
        "Gateway",
        typeof(ICodingEscalationDecisionGateway),
        typeof(CodingEscalationDecisionGatewayContext),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.Inherits));

    public static void SetGateway(DependencyObject element, ICodingEscalationDecisionGateway? value)
    {
        ArgumentNullException.ThrowIfNull(element);
        element.SetValue(GatewayProperty, value);
    }

    public static ICodingEscalationDecisionGateway? GetGateway(DependencyObject element)
    {
        ArgumentNullException.ThrowIfNull(element);
        return element.GetValue(GatewayProperty) as ICodingEscalationDecisionGateway;
    }
}
