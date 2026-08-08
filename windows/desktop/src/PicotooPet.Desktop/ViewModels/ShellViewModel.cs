using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Versioning;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>把真实会话快照适配为冻结导航、全局状态和当前页面。</summary>
public sealed class ShellViewModel : ObservableObject, IDisposable
{
    private readonly ControlCenterSession? _session;
    private readonly IUiDispatcher? _dispatcher;
    private ControlCenterSessionSnapshot? _snapshot;
    private IReadOnlyList<NavigationItem> _navigationItems;
    private NavigationItem _selectedNavigationItem;
    private NavigationRoute _currentRoute;
    private PageViewModel _currentPage;
    private string _connectionText;
    private string _connectionMessage;
    private string _approvalText;
    private string _statusMessage;
    private bool _disposed;

    /// <summary>创建绑定真实 Session 的运行时 Shell。</summary>
    public ShellViewModel(
        ControlCenterSession session,
        IUiDispatcher dispatcher)
    {
        _session    = session ?? throw new ArgumentNullException(nameof(session));
        _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        _snapshot   = session.Snapshot;
        _navigationItems = BuildNavigation(_snapshot.State.Capabilities.Features);
        _selectedNavigationItem = FindItem(_navigationItems, NavigationRoute.Dashboard);
        _currentRoute      = NavigationRoute.Dashboard;
        _currentPage       = CreatePage(_currentRoute, _snapshot);
        _connectionText    = FormatConnection(_snapshot.State.Connection.State);
        _connectionMessage = FormatConnectionMessage(_snapshot);
        _approvalText      = FormatApproval(_snapshot.State.Capabilities);
        _statusMessage     = _snapshot.StatusMessage;
        session.SnapshotChanged += OnSessionSnapshotChanged;
    }

    private ShellViewModel(ControlCenterCapabilities capabilities)
    {
        ArgumentNullException.ThrowIfNull(capabilities);
        _navigationItems = BuildNavigation(capabilities);
        _selectedNavigationItem = FindItem(_navigationItems, NavigationRoute.Dashboard);
        _currentRoute      = NavigationRoute.Dashboard;
        _currentPage       = CreateStaticPage(_currentRoute, capabilities);
        _connectionText    = "离线";
        _connectionMessage = "Smoke test 模式未连接 Mac Core。";
        _approvalText      = capabilities.ApprovalList ? "审批能力可用" : "审批能力未启用";
        _statusMessage     = "确定性导航测试。";
    }

    /// <summary>Windows 主窗口用户可见标题。</summary>
    public string WindowTitle => ProductVersionInfo.WindowTitle;

    /// <summary>Control Center 左上角用户可见版本副标题。</summary>
    public string ControlCenterSubtitle => ProductVersionInfo.ControlCenterSubtitle;

    /// <summary>十个冻结的一级导航项。</summary>
    public IReadOnlyList<NavigationItem> NavigationItems
    {
        get => _navigationItems;
        private set => SetProperty(ref _navigationItems, value);
    }

    /// <summary>当前选中的导航项；WPF 重建 ItemsSource 时的瞬时 null 不改变现有页面。</summary>
    public NavigationItem SelectedNavigationItem
    {
        get => _selectedNavigationItem;
        set
        {
            if (value is null)
            {
                // ListBox 在 NavigationItems 替换时会先清空选择，再恢复同路由项。
                // 该瞬时状态不是用户导航，不应抛出进程级异常或清除当前页面。
                return;
            }
            if (!SetProperty(ref _selectedNavigationItem, value))
            {
                return;
            }
            CurrentRoute = value.Route;
            CurrentPage  = CreateCurrentPage(value.Route);
        }
    }

    /// <summary>当前选中的路由。</summary>
    public NavigationRoute CurrentRoute
    {
        get => _currentRoute;
        private set => SetProperty(ref _currentRoute, value);
    }

    /// <summary>当前页面；不可用路由仍展示原因、后续步骤和用户动作。</summary>
    public PageViewModel CurrentPage
    {
        get => _currentPage;
        private set => SetProperty(ref _currentPage, value);
    }

    /// <summary>顶部全局连接状态。</summary>
    public string ConnectionText
    {
        get => _connectionText;
        private set => SetProperty(ref _connectionText, value);
    }

    /// <summary>底部连接和错误说明。</summary>
    public string ConnectionMessage
    {
        get => _connectionMessage;
        private set => SetProperty(ref _connectionMessage, value);
    }

    /// <summary>顶部审批能力说明；未接入时不伪造待审批数量。</summary>
    public string ApprovalText
    {
        get => _approvalText;
        private set => SetProperty(ref _approvalText, value);
    }

    /// <summary>当前会话操作说明。</summary>
    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    /// <summary>创建不依赖窗口或网络的确定性 Shell 模型。</summary>
    public static ShellViewModel CreateForSmokeTest(
        ControlCenterCapabilities capabilities) => new(capabilities);

    /// <summary>按路由切换页面；导航项可用性只限制动作，不隐藏解释。</summary>
    public void Navigate(NavigationRoute route)
    {
        var item = FindItem(NavigationItems, route);
        if (!ReferenceEquals(SelectedNavigationItem, item))
        {
            SelectedNavigationItem = item;
            return;
        }
        CurrentRoute = route;
        CurrentPage  = CreateCurrentPage(route);
    }

    /// <summary>用安全说明页替换故障路由，同时保留其他一级导航能力。</summary>
    public void ShowNavigationFailure(NavigationRoute route)
    {
        var item = FindItem(NavigationItems, route);
        if (!ReferenceEquals(_selectedNavigationItem, item))
        {
            _selectedNavigationItem = item;
            RaisePropertyChanged(nameof(SelectedNavigationItem));
        }

        CurrentRoute = route;
        CurrentPage = new EmptyStatePageViewModel(
            $"{item.Title}暂时不可用",
            "页面加载时发生故障，Control Center 已隔离该页面。",
            "错误摘要已写入本地脱敏日志；你可以切换到其他页面继续使用。",
            "稍后重新打开此页面；无需重启或重新安装。");
        StatusMessage = $"{item.Title}页面加载失败，其他页面仍可使用。";
    }

    private PageViewModel CreateCurrentPage(NavigationRoute route) =>
        _snapshot is null
            ? CreateStaticPage(route, ControlCenterCapabilities.Legacy22)
            : CreatePage(route, _snapshot);

    private PageViewModel CreatePage(
        NavigationRoute route,
        ControlCenterSessionSnapshot snapshot) => route switch
    {
        NavigationRoute.Dashboard => new OverviewPageViewModel(
            snapshot,
            FormatConnection(snapshot.State.Connection.State)),
        NavigationRoute.Projects when _session is not null =>
            new ProjectsPageViewModel(_session),
        NavigationRoute.TaskCenter when _session is not null =>
            new TaskCenterPageViewModel(_session, snapshot),
        NavigationRoute.Results when _session is not null =>
            new ResultsPageViewModel(_session, snapshot),
        NavigationRoute.Approvals when _session is not null =>
            new ApprovalsPageViewModel(_session),
        NavigationRoute.CloudDevelopment when _session is not null =>
            new CloudDevelopmentPageViewModel(
                new ControlCenterHandoffGateway(_session)),
        NavigationRoute.CloudDevelopment => new CloudDevelopmentPageViewModel(),
        NavigationRoute.Automation when _session is not null =>
            new AutomationPageViewModel(_session),
        NavigationRoute.Health when _session is not null =>
            new HealthPageViewModel(_session),
        NavigationRoute.Diagnostics when _session is not null =>
            new DiagnosticsPageViewModel(_session),
        NavigationRoute.Settings => new SettingsPageViewModel(snapshot.MacBaseUrl),
        _ => CreateStaticPage(route, snapshot.State.Capabilities.Features),
    };

    private static NavigationItem[] BuildNavigation(
        ControlCenterCapabilities capabilities) =>
        new NavigationItem[]
        {
            Item(
                NavigationRoute.Dashboard,
                "总览",
                capabilities.Dashboard,
                "当前提供真实连接、Worker 和任务摘要；完整 Dashboard 聚合尚未声明。"),
            Item(
                NavigationRoute.Projects,
                "项目",
                capabilities.Projects,
                "Mac Core 尚未声明项目目录能力。"),
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
                capabilities.ApprovalList && capabilities.ApprovalDigest,
                "Mac Core 尚未同时声明审批列表和摘要决策能力。"),
            Item(
                NavigationRoute.CloudDevelopment,
                "云端开发",
                isAvailable: true,
                "Handoff / Return Contract v1 已冻结；Provider 尚未配置。"),
            Item(
                NavigationRoute.Automation,
                "自动化",
                capabilities.WorkflowAutomation,
                "Mac Core 尚未声明耐久工作流自动化能力。"),
            Item(
                NavigationRoute.Health,
                "健康",
                capabilities.AutomationHealth,
                "Mac Core 尚未声明结构化平台健康能力。"),
            Item(
                NavigationRoute.Diagnostics,
                "诊断",
                capabilities.AutomationDiagnostics,
                "Mac Core 尚未声明结构化自动化诊断能力。"),
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

    private static NavigationItem FindItem(
        IReadOnlyList<NavigationItem> items,
        NavigationRoute route) =>
        items.Single(item => item.Route == route);

    private static PageViewModel CreateStaticPage(
        NavigationRoute route,
        ControlCenterCapabilities capabilities) => route switch
    {
        NavigationRoute.Dashboard => new EmptyStatePageViewModel(
            "总览",
            "当前版本尚未声明完整 Dashboard 能力。",
            "运行时 Shell 将展示真实连接、Worker、任务和健康摘要。",
            "你现在不需要操作。"),
        NavigationRoute.Projects => new EmptyStatePageViewModel(
            "项目",
            "当前服务尚未声明项目目录能力。",
            "升级 Mac Core 后项目页将读取真实项目元数据。",
            "你现在不需要操作。"),
        NavigationRoute.TaskCenter => TaskCenterPageViewModel.CreateForSmokeTest(
            Array.Empty<TaskRecord>(),
            WorkerSnapshot.NotDeployed),
        NavigationRoute.Results => ResultsPageViewModel.CreateForSmokeTest(
            Array.Empty<TaskRecord>()),
        NavigationRoute.Approvals when capabilities.ApprovalList && capabilities.ApprovalDigest =>
            ApprovalsPageViewModel.CreateForSmokeTest(Array.Empty<ApprovalRecord>()),
        NavigationRoute.Approvals => new EmptyStatePageViewModel(
            "审批",
            "Mac Core 尚未同时声明审批列表和审批摘要能力。",
            "升级 Core 后页面将接入只读审批队列和显式摘要决策。",
            "你现在不需要操作。"),
        NavigationRoute.CloudDevelopment => new CloudDevelopmentPageViewModel(),
        NavigationRoute.Automation => new EmptyStatePageViewModel(
            "自动化",
            "当前服务尚未声明耐久工作流自动化能力。",
            "升级 Mac Core 后页面将接入工作流、步骤和安全控制动作。",
            "你现在不需要操作。"),
        NavigationRoute.Health => new EmptyStatePageViewModel(
            "健康",
            "当前服务尚未声明结构化平台健康能力。",
            "升级 Mac Core 后页面将显示数据库、队列和 Worker capability。",
            "你现在不需要操作。"),
        NavigationRoute.Diagnostics => new EmptyStatePageViewModel(
            "诊断",
            "当前服务尚未声明结构化自动化诊断能力。",
            "升级 Mac Core 后页面将显示安全错误元数据和 Trace ID。",
            "你现在不需要操作。"),
        NavigationRoute.Settings => new SettingsPageViewModel(DesktopSettings.Default.MacBaseUrl),
        _ => throw new ArgumentOutOfRangeException(nameof(route), route, "未知导航路由。"),
    };

    private void OnSessionSnapshotChanged(
        object? sender,
        ControlCenterSessionSnapshot snapshot)
    {
        var dispatcher = _dispatcher;
        if (dispatcher is null)
        {
            ApplySnapshot(snapshot);
            return;
        }
        _ = dispatcher.InvokeAsync(
            () => ApplySnapshot(snapshot),
            CancellationToken.None);
    }

    private void ApplySnapshot(ControlCenterSessionSnapshot snapshot)
    {
        _snapshot = snapshot;
        var route = CurrentRoute;
        NavigationItems = BuildNavigation(snapshot.State.Capabilities.Features);
        _selectedNavigationItem = FindItem(NavigationItems, route);
        RaisePropertyChanged(nameof(SelectedNavigationItem));
        ConnectionText    = FormatConnection(snapshot.State.Connection.State);
        ConnectionMessage = FormatConnectionMessage(snapshot);
        ApprovalText      = FormatApproval(snapshot.State.Capabilities);
        StatusMessage     = snapshot.StatusMessage;

        if (route == NavigationRoute.TaskCenter
            && CurrentPage is TaskCenterPageViewModel taskCenter)
        {
            taskCenter.UpdateSnapshot(snapshot);
        }
        else if (route == NavigationRoute.Results
            && CurrentPage is ResultsPageViewModel results)
        {
            results.UpdateSnapshot(snapshot);
        }
        else if (route == NavigationRoute.Approvals
            && CurrentPage is ApprovalsPageViewModel)
        {
            // 审批页面维护自己的选择、原因和幂等操作；普通连接快照不得替换页面实例。
        }
        else if (route == NavigationRoute.CloudDevelopment
            && CurrentPage is CloudDevelopmentPageViewModel)
        {
            // Handoff 表单、预览和幂等操作由页面维护；普通连接快照不得清空页面实例。
        }
        else if (route is NavigationRoute.Projects
                 or NavigationRoute.Automation
                 or NavigationRoute.Health
                 or NavigationRoute.Diagnostics)
        {
            // 新平台页各自通过显式刷新读取较大事实集；连接心跳不得重建页面并清空选择。
        }
        else
        {
            CurrentPage = CreatePage(route, snapshot);
        }
    }

    private static string FormatConnection(ConnectionState state) => state switch
    {
        ConnectionState.Online               => "在线",
        ConnectionState.Connecting           => "连接中",
        ConnectionState.Reconnecting         => "正在重连",
        ConnectionState.AuthenticationFailed => "认证失败",
        ConnectionState.Faulted              => "连接故障",
        _                                    => "离线",
    };

    private static string FormatConnectionMessage(ControlCenterSessionSnapshot snapshot)
    {
        var error = snapshot.State.Connection.LastError;
        return string.IsNullOrWhiteSpace(error)
            ? snapshot.StatusMessage
            : $"{snapshot.StatusMessage} · {error}";
    }

    private static string FormatApproval(CapabilitySnapshot capabilities) =>
        capabilities.Features.ApprovalList && capabilities.Features.ApprovalDigest
            ? "审批能力已接入"
            : "审批能力未启用";

    /// <summary>取消会话快照订阅；网络资源由 ControlCenterSession 统一释放。</summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        if (_session is not null)
        {
            _session.SnapshotChanged -= OnSessionSnapshotChanged;
        }
    }
}
