using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>维护冻结导航、能力可用性和当前解释性页面。</summary>
public sealed class ShellViewModel : ObservableObject
{
    private NavigationRoute _currentRoute;
    private PageViewModel _currentPage;

    private ShellViewModel(ControlCenterCapabilities capabilities)
    {
        ArgumentNullException.ThrowIfNull(capabilities);

        NavigationItems = BuildNavigation(capabilities);
        _currentRoute    = NavigationRoute.Dashboard;
        _currentPage     = CreatePage(_currentRoute);
    }

    /// <summary>十个冻结的一级导航项。</summary>
    public IReadOnlyList<NavigationItem> NavigationItems { get; }

    /// <summary>当前选中的路由。</summary>
    public NavigationRoute CurrentRoute
    {
        get => _currentRoute;
        private set => SetProperty(ref _currentRoute, value);
    }

    /// <summary>当前页面；不可用路由仍可展示完整原因和后续步骤。</summary>
    public PageViewModel CurrentPage
    {
        get => _currentPage;
        private set => SetProperty(ref _currentPage, value);
    }

    /// <summary>创建不依赖窗口或网络的确定性 Shell 模型。</summary>
    public static ShellViewModel CreateForSmokeTest(
        ControlCenterCapabilities capabilities) => new(capabilities);

    /// <summary>切换页面；能力状态只限制操作，不隐藏解释信息。</summary>
    public void Navigate(NavigationRoute route)
    {
        CurrentRoute = route;
        CurrentPage  = CreatePage(route);
    }

    private static IReadOnlyList<NavigationItem> BuildNavigation(
        ControlCenterCapabilities capabilities) =>
        new NavigationItem[]
        {
            Item(
                NavigationRoute.Dashboard,
                "总览",
                capabilities.Dashboard,
                "Mac Core 尚未声明 Dashboard 能力。"),
            Item(
                NavigationRoute.Projects,
                "项目",
                isAvailable: false,
                "Slice A 只冻结项目导航，尚未提供项目目录。"),
            Item(
                NavigationRoute.TaskCenter,
                "任务中心",
                capabilities.DurableQueue,
                "需要 Mac Core 的耐久任务队列能力。"),
            Item(
                NavigationRoute.Results,
                "结果",
                capabilities.ResultList,
                "Mac Core 尚未声明结果列表能力。"),
            Item(
                NavigationRoute.Approvals,
                "审批",
                capabilities.ApprovalList,
                "Mac Core 尚未声明审批列表能力。"),
            Item(
                NavigationRoute.CloudDevelopment,
                "云端开发",
                isAvailable: false,
                "当前只冻结 Handoff / Return Contract，未安装或调用外部 Provider。"),
            Item(
                NavigationRoute.Automation,
                "自动化",
                isAvailable: false,
                "自动化策略尚未进入 Slice A。"),
            Item(
                NavigationRoute.Health,
                "健康",
                capabilities.HealthDetailed,
                "Mac Core 尚未声明详细健康能力。"),
            Item(
                NavigationRoute.Diagnostics,
                "诊断",
                capabilities.LogsQuery,
                "Mac Core 尚未声明日志查询能力。"),
            Item(
                NavigationRoute.Settings,
                "设置",
                isAvailable: true,
                "复用现有 Mac 地址与 Credential Manager 配对行为。"),
        };

    private static NavigationItem Item(
        NavigationRoute route,
        string title,
        bool isAvailable,
        string unavailableMessage) => new(
            route,
            title,
            isAvailable,
            isAvailable ? "当前能力可用。" : unavailableMessage);

    private static PageViewModel CreatePage(NavigationRoute route) => route switch
    {
        NavigationRoute.Dashboard => new EmptyStatePageViewModel(
            "总览",
            "当前版本尚未声明 Dashboard 能力。",
            "后续切片将接入真实连接、任务和健康摘要。",
            "你现在不需要操作。"),
        NavigationRoute.Projects => new EmptyStatePageViewModel(
            "项目",
            "当前 Slice A 只冻结了项目导航，尚未提供项目目录或详情。",
            "后续切片将先定义项目快照和只读列表。",
            "你现在不需要操作。"),
        NavigationRoute.TaskCenter => new EmptyStatePageViewModel(
            "任务中心",
            "现有 2.2 耐久任务列表能力已保留，新的 Shell 页面尚未接入。",
            "Task 8 将把真实任务快照接入 Control Center。",
            "你现在不需要操作。"),
        NavigationRoute.Results => new EmptyStatePageViewModel(
            "结果",
            "Mac Core 尚未声明结果列表和预览能力。",
            "后续切片将先加入只读结果清单，再加入安全预览。",
            "你现在不需要操作。"),
        NavigationRoute.Approvals => new EmptyStatePageViewModel(
            "审批",
            "Mac Core 尚未声明审批列表或审批摘要能力。",
            "后续切片将先接入只读审批队列，再加入显式审批动作。",
            "你现在不需要操作。"),
        NavigationRoute.CloudDevelopment => new EmptyStatePageViewModel(
            "云端开发",
            "当前版本只冻结了 Handoff / Return Contract，尚未安装或调用外部 Provider。",
            "Phase 10A 将先加入包预览和审批；Phase 10B 才加入 Dev Broker。",
            "你现在不需要操作。"),
        NavigationRoute.Automation => new EmptyStatePageViewModel(
            "自动化",
            "自动化策略和执行器尚未进入 Slice A。",
            "后续切片将先冻结策略合同和审批边界。",
            "你现在不需要操作。"),
        NavigationRoute.Health => new EmptyStatePageViewModel(
            "健康",
            "当前只保留轻量 health 快照，尚未声明详细健康能力。",
            "后续切片将接入分组件健康状态和时间戳。",
            "你现在不需要操作。"),
        NavigationRoute.Diagnostics => new EmptyStatePageViewModel(
            "诊断",
            "Mac Core 尚未声明日志查询能力。",
            "后续切片将先加入脱敏、只读和有界的诊断查询。",
            "你现在不需要操作。"),
        NavigationRoute.Settings => new EmptyStatePageViewModel(
            "设置",
            "现有 Mac 地址与 Credential Manager 令牌行为保持不变，新的设置页尚未接入。",
            "Task 8 将复用现有设置和配对路径。",
            "你现在不需要操作。"),
        _ => throw new ArgumentOutOfRangeException(nameof(route), route, "未知导航路由。"),
    };
}
