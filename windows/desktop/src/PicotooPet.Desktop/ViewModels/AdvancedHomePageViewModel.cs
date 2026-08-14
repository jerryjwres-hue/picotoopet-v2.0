using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>高级功能落地页链接；只引用已有固定路由。</summary>
public sealed record AdvancedRouteLink(
    string Group,
    string Title,
    NavigationRoute Route);

/// <summary>把历史工程页面收纳到一个高级入口，不删除任何既有能力。</summary>
public sealed class AdvancedHomePageViewModel : PageViewModel
{
    public AdvancedHomePageViewModel()
        : base("高级")
    {
    }

    public IReadOnlyList<AdvancedRouteLink> Links { get; } = new AdvancedRouteLink[]
    {
        new("业务与执行", "项目", NavigationRoute.Projects),
        new("业务与执行", "任务中心", NavigationRoute.TaskCenter),
        new("业务与执行", "结果", NavigationRoute.Results),
        new("业务与执行", "业务自动化", NavigationRoute.BusinessAutomation),
        new("业务与执行", "自动化", NavigationRoute.Automation),
        new("人工治理", "审批", NavigationRoute.Approvals),
        new("人工治理", "质量 / Shadow / Promotion", NavigationRoute.BusinessAutomation),
        new("系统与运维", "健康", NavigationRoute.Health),
        new("系统与运维", "诊断", NavigationRoute.Diagnostics),
        new("开发与配置", "云端开发", NavigationRoute.CloudDevelopment),
        new("开发与配置", "设置", NavigationRoute.Settings),
    };
}
