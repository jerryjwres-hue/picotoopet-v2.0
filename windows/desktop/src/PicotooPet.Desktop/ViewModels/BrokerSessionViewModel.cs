using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 10B-B approved Handoff、Broker Session 与固定安全预览状态。</summary>
public sealed class BrokerSessionViewModel : ObservableObject
{
    private readonly IBrokerSessionGateway? _gateway;
    private IReadOnlyList<HandoffRecord> _approvedHandoffs;
    private HandoffRecord? _selectedHandoff;
    private IReadOnlyList<BrokerSessionRecord> _recentSessions;
    private BrokerSessionRecord? _selectedRecentSession;
    private BrokerSessionRecord? _selectedSession;
    private string _statusMessage;
    private bool _isPreviewVisible;
    private bool _isBusy;

    /// <summary>创建设计时与真实 WPF 布局测试使用的确定性安全投影。</summary>
    public BrokerSessionViewModel()
        : this(gateway: null, initializeSmoke: true)
    {
    }

    /// <summary>创建绑定受限 Broker 网关的运行时模型。</summary>
    public BrokerSessionViewModel(IBrokerSessionGateway gateway)
        : this(
            gateway ?? throw new ArgumentNullException(nameof(gateway)),
            initializeSmoke: false)
    {
    }

    private BrokerSessionViewModel(
        IBrokerSessionGateway? gateway,
        bool initializeSmoke)
    {
        _gateway          = gateway;
        _approvedHandoffs = Array.Empty<HandoffRecord>();
        _recentSessions   = Array.Empty<BrokerSessionRecord>();
        _statusMessage    = "Phase 10B-B 只运行内置 Mock Provider 和应用自有沙盒。";
        RefreshCommand = new AsyncRelayCommand(
            () => RefreshAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy);
        StartCommand = new AsyncRelayCommand(
            () => StartAsync(CancellationToken.None),
            HandleCommandError,
            () => CanStart);
        CancelCommand = new AsyncRelayCommand(
            () => CancelAsync(CancellationToken.None),
            HandleCommandError,
            () => CanCancel);

        if (initializeSmoke)
        {
            var handoff = CreateSmokeHandoff();
            var session = CreateSmokeSession();
            ApprovedHandoffs     = [handoff];
            SelectedHandoff      = handoff;
            RecentSessions       = [session];
            SelectedRecentSession = session;
            SelectedSession      = session;
            IsPreviewVisible     = true;
        }
    }

    /// <summary>面板必须持续显示的不可突破边界。</summary>
    public string SafetyNotice =>
        $"固定 Provider · 应用自有沙盒 · {SelectedSession?.TimeoutSeconds ?? 30} 秒硬超时；"
        + "不接收路径、命令、凭据或文件，不调用真实 Provider，不运行项目测试/构建或 Git 写操作。";

    public AsyncRelayCommand RefreshCommand { get; }

    public AsyncRelayCommand StartCommand { get; }

    public AsyncRelayCommand CancelCommand { get; }

    public IReadOnlyList<HandoffRecord> ApprovedHandoffs
    {
        get => _approvedHandoffs;
        private set => SetProperty(ref _approvedHandoffs, value);
    }

    public HandoffRecord? SelectedHandoff
    {
        get => _selectedHandoff;
        set
        {
            if (value is null && _selectedHandoff is not null)
            {
                // ItemsSource 替换时的瞬时 null 不是用户取消选择。
                return;
            }
            if (SetProperty(ref _selectedHandoff, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public IReadOnlyList<BrokerSessionRecord> RecentSessions
    {
        get => _recentSessions;
        private set => SetProperty(ref _recentSessions, value);
    }

    public BrokerSessionRecord? SelectedRecentSession
    {
        get => _selectedRecentSession;
        set
        {
            if (value is null && _selectedRecentSession is not null)
            {
                // ListBox 在 ItemsSource 替换时会短暂回写 null；保留当前逻辑预览。
                return;
            }
            if (!SetProperty(ref _selectedRecentSession, value))
            {
                return;
            }
            if (value is not null)
            {
                SelectedSession   = value;
                IsPreviewVisible  = true;
                StatusMessage     = "已加载 Broker Session 固定安全投影。";
            }
        }
    }

    /// <summary>与列表选择分离的 Session 预览，用于抵御 ItemsSource 替换。</summary>
    public BrokerSessionRecord? SelectedSession
    {
        get => _selectedSession;
        private set
        {
            if (SetProperty(ref _selectedSession, value))
            {
                RaisePropertyChanged(nameof(SafetyNotice));
                RaisePropertyChanged(nameof(ChangedFileSummary));
                RaiseActionProperties();
            }
        }
    }

    public string ChangedFileSummary =>
        SelectedSession?.Status is "completed" or "quarantined"
            ? "固定 Return：1 个 docs/mock-provider-proof.txt 文本变更"
            : "固定上限：1 个 docs/mock-provider-proof.txt 文本变更";

    public bool IsPreviewVisible
    {
        get => _isPreviewVisible;
        private set => SetProperty(ref _isPreviewVisible, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public bool CanStart =>
        !IsBusy
        && _gateway is not null
        && SelectedHandoff is { Status: "approved" };

    public bool CanCancel =>
        _gateway is not null
        && SelectedSession?.Status is "reserved" or "running" or "returning";

    /// <summary>首次打开时并发读取 approved Handoff 和最近 Broker Session。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在读取 approved Handoff 和 Broker Session……";
        try
        {
            var handoffsTask = _gateway.GetHandoffsAsync(cancellationToken);
            var sessionsTask = _gateway.GetBrokerSessionsAsync(cancellationToken);
            await Task.WhenAll(handoffsTask, sessionsTask).ConfigureAwait(true);
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            ApplySessions(await sessionsTask.ConfigureAwait(true));
            StatusMessage =
                $"已加载 {ApprovedHandoffs.Count} 条 approved Handoff 和 {RecentSessions.Count} 条 Broker Session。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "加载失败；已有 Broker 安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>刷新安全事实；等价 session_id 继续复用原预览对象。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在刷新 Broker Session 状态……";
        try
        {
            var handoffsTask = _gateway.GetHandoffsAsync(cancellationToken);
            var sessionsTask = _gateway.GetBrokerSessionsAsync(cancellationToken);
            await Task.WhenAll(handoffsTask, sessionsTask).ConfigureAwait(true);
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            ApplySessions(await sessionsTask.ConfigureAwait(true));
            StatusMessage = "Broker 状态已刷新；已有安全预览保持可见。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "刷新失败；已有 Broker 安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>启动固定 Mock Broker，并实时接收不含 capability 的状态投影。</summary>
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能运行 Broker。");
        var handoff = SelectedHandoff
            ?? throw new InvalidOperationException("请先选择一个 approved Handoff。");
        if (!CanStart)
        {
            throw new InvalidOperationException("当前状态不能启动 Mock Dev Broker。");
        }

        var idempotencyKey = $"windows-mock-broker-{handoff.HandoffId}-{Guid.NewGuid():N}";
        var progress = new Progress<BrokerSessionRecord>(record =>
        {
            UpsertAndSelect(record);
            StatusMessage = record.Status switch
            {
                "reserved"  => "Broker Session 已预留，准备启动固定子进程……",
                "running"   => "内置 Mock Provider 正在应用自有沙盒运行……",
                "returning" => "正在向 Mac Core 提交有界 Return……",
                _           => StatusMessage,
            };
        });

        IsBusy        = true;
        StatusMessage = "正在预留固定 Mock Broker Session……";
        try
        {
            var terminal = await gateway.RunMockBrokerAsync(
                handoff,
                idempotencyKey,
                progress,
                cancellationToken).ConfigureAwait(true);
            UpsertAndSelect(terminal);
            StatusMessage = terminal.Status switch
            {
                "completed"   => "Mock Broker 已完成；Return 仅通过合同验证，未运行项目测试或构建。",
                "cancelled"   => "Mock Broker 已取消，Job Object 进程树已关闭。",
                "timed_out"   => "Mock Broker 已按固定 30 秒时限终止。",
                "failed"      => "Mock Broker 子进程失败；只保留固定错误码。",
                "quarantined" => "Mock Return 已整体隔离；不显示不可信正文。",
                _             => "Broker Session 状态已更新。",
            };
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>取消当前活动 Session；本地进程树与 Mac Core 事实同时收敛。</summary>
    public async Task CancelAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能取消 Broker。");
        var session = SelectedSession
            ?? throw new InvalidOperationException("当前没有可取消的 Broker Session。");
        if (!CanCancel)
        {
            throw new InvalidOperationException("当前 Broker Session 已不是可取消状态。");
        }

        StatusMessage = "正在取消 Broker Session 并关闭完整进程树……";
        var cancelled = await gateway.CancelBrokerAsync(
            session.SessionId,
            $"windows-mock-broker-cancel-{session.SessionId}-{Guid.NewGuid():N}",
            cancellationToken).ConfigureAwait(true);
        UpsertAndSelect(cancelled);
        StatusMessage = "Broker Session 已取消；安全预览保持可见。";
    }

    private void ApplyHandoffs(IReadOnlyList<HandoffRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var previous   = SelectedHandoff;
        var selectedId = previous?.HandoffId;
        var approved = records
            .Where(item => string.Equals(item.Status, "approved", StringComparison.Ordinal))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        ApprovedHandoffs = approved;
        var refreshed = selectedId is null
            ? approved.FirstOrDefault()
            : approved.FirstOrDefault(item => string.Equals(
                item.HandoffId,
                selectedId,
                StringComparison.Ordinal));
        if (previous is not null
            && refreshed is not null
            && HandoffEquivalent(previous, refreshed))
        {
            _selectedHandoff = previous;
            RaisePropertyChanged(nameof(SelectedHandoff));
            RaiseActionProperties();
            return;
        }
        _selectedHandoff = refreshed ?? approved.FirstOrDefault();
        RaisePropertyChanged(nameof(SelectedHandoff));
        RaiseActionProperties();
    }

    private void ApplySessions(IReadOnlyList<BrokerSessionRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var previous   = SelectedSession;
        var selectedId = previous?.SessionId;
        var ordered = records
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        RecentSessions = ordered;
        var refreshed = selectedId is null
            ? ordered.FirstOrDefault()
            : ordered.FirstOrDefault(item => string.Equals(
                item.SessionId,
                selectedId,
                StringComparison.Ordinal));
        if (previous is not null
            && refreshed is not null
            && SessionEquivalent(previous, refreshed))
        {
            _selectedRecentSession = refreshed;
            RaisePropertyChanged(nameof(SelectedRecentSession));
            SelectedSession  = previous;
            IsPreviewVisible = true;
            return;
        }
        _selectedRecentSession = refreshed ?? ordered.FirstOrDefault();
        RaisePropertyChanged(nameof(SelectedRecentSession));
        if (_selectedRecentSession is not null)
        {
            SelectedSession  = _selectedRecentSession;
            IsPreviewVisible = true;
        }
    }

    private void UpsertAndSelect(BrokerSessionRecord record)
    {
        var records = RecentSessions
            .Where(item => !string.Equals(
                item.SessionId,
                record.SessionId,
                StringComparison.Ordinal))
            .Append(record)
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        RecentSessions        = records;
        SelectedRecentSession = record;
        SelectedSession       = record;
        IsPreviewVisible      = true;
    }

    private static bool HandoffEquivalent(HandoffRecord left, HandoffRecord right) =>
        string.Equals(left.HandoffId, right.HandoffId, StringComparison.Ordinal)
        && string.Equals(left.Status, right.Status, StringComparison.Ordinal)
        && string.Equals(left.RequestDigest, right.RequestDigest, StringComparison.Ordinal)
        && string.Equals(left.PackageDigest, right.PackageDigest, StringComparison.Ordinal);

    private static bool SessionEquivalent(
        BrokerSessionRecord left,
        BrokerSessionRecord right) =>
        string.Equals(left.SessionId, right.SessionId, StringComparison.Ordinal)
        && string.Equals(left.Status, right.Status, StringComparison.Ordinal)
        && string.Equals(left.ReturnId, right.ReturnId, StringComparison.Ordinal)
        && string.Equals(left.SandboxDigest, right.SandboxDigest, StringComparison.Ordinal)
        && string.Equals(left.FailureCode, right.FailureCode, StringComparison.Ordinal)
        && left.EventCount == right.EventCount;

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanStart));
        RaisePropertyChanged(nameof(CanCancel));
        RefreshCommand.NotifyCanExecuteChanged();
        StartCommand.NotifyCanExecuteChanged();
        CancelCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception)
    {
        StatusMessage = FormatError(
            "Broker 操作失败；已有安全预览已保留。",
            exception);
    }

    private static bool IsBoundedOperationalError(Exception exception) =>
        exception is ApiException
            or BrokerProcessException
            or InvalidOperationException
            or IOException;

    private static string FormatError(string prefix, Exception exception)
    {
        var message = exception.Message.Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (message.Length > 180)
        {
            message = message[..180] + "…";
        }
        return string.IsNullOrWhiteSpace(message)
            ? prefix
            : $"{prefix} {message}";
    }

    private static HandoffRecord CreateSmokeHandoff() => new(
        "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "Mock Dev Broker 验证",
        "验证固定沙盒、进程边界和 Return 导回。",
        "approved",
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase10b-mock-dev-broker",
        "d3ad0c5d4d2d09b277078d0d03b6ddaeab402d13",
        "internal",
        1,
        1,
        ["python-regression", "windows-wpf-behavior", "mac-core-arm64"],
        "20 turns · 30 秒 Broker · 1 并发 · 无外部 Provider",
        new string('a', 64),
        new string('b', 64),
        "approval-smoke",
        new DateTimeOffset(2026, 8, 6, 0, 0, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 1, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 30, 0, TimeSpan.Zero),
        ["No external Provider execution."]);

    private static BrokerSessionRecord CreateSmokeSession() => new(
        "153704fb-3ce7-4368-ae0e-9520c21ec022",
        "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
        "completed",
        "local-mock-dev-broker",
        30,
        new string('a', 64),
        new string('b', 64),
        "253704fb-3ce7-4368-ae0e-9520c21ec022",
        4,
        new string('c', 64),
        null,
        new DateTimeOffset(2026, 8, 6, 0, 2, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 3, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 3, 0, TimeSpan.Zero),
        "仅完成固定 Mock Provider 沙盒与 Return 合同验证。");
}
