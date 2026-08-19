using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>人工额度确认、Core 创建的 Codex Session 进度与紧急取消的原生模型。</summary>
public sealed class ProviderSessionViewModel : ObservableObject
{
    private static readonly IReadOnlyList<string> UsageChoices = Array.AsReadOnly(
        ["confirmed_available", "confirmed_low", "confirmed_exhausted", "unknown"]);

    private static readonly HashSet<string> TerminalStatuses = new(StringComparer.Ordinal)
    {
        "ready_for_review",
        "cancelled",
        "timed_out",
        "stopped_by_budget",
        "stopped_by_policy",
        "provider_failed",
        "return_quarantined",
        "validation_failed",
        "failed",
    };

    private readonly IProviderSessionGateway? _gateway;
    private ProviderStatusRecord _providerStatus;
    private IReadOnlyList<HandoffRecord> _eligibleHandoffs;
    private HandoffRecord? _selectedHandoff;
    private ProviderUsageConfirmationRecord? _latestConfirmation;
    private IReadOnlyList<ProviderSessionRecord> _recentSessions;
    private ProviderSessionRecord? _selectedRecentSession;
    private ProviderSessionRecord? _selectedSession;
    private string _selectedUsageStatus = "unknown";
    private string _statusMessage;
    private bool _isBusy;

    public ProviderSessionViewModel()
        : this(gateway: null, initializeSmoke: true)
    {
    }

    public ProviderSessionViewModel(IProviderSessionGateway gateway)
        : this(gateway ?? throw new ArgumentNullException(nameof(gateway)), initializeSmoke: false)
    {
    }

    private ProviderSessionViewModel(IProviderSessionGateway? gateway, bool initializeSmoke)
    {
        _gateway = gateway;
        _providerStatus = new ProviderStatusRecord(
            "codex",
            "unavailable",
            RealExecutionDefault: false,
            UsageMachineReadable: false,
            "mac-worker",
            "Mac Worker 尚未报告 Codex CLI 就绪状态。");
        _eligibleHandoffs = Array.Empty<HandoffRecord>();
        _recentSessions   = Array.Empty<ProviderSessionRecord>();
        _statusMessage =
            "外部 Coding Session 由 Mac Core Frugal 仲裁器推进；Windows 只确认额度、查看状态和紧急取消。";

        RefreshCommand = new AsyncRelayCommand(
            () => RefreshAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy);
        ConfirmUsageCommand = new AsyncRelayCommand(
            () => ConfirmUsageAsync(CancellationToken.None),
            HandleCommandError,
            () => CanConfirmUsage);
        CancelSessionCommand = new AsyncRelayCommand(
            () => CancelSelectedSessionAsync(CancellationToken.None),
            HandleCommandError,
            () => CanCancelSession);

        if (initializeSmoke)
        {
            var handoff = CreateSmokeHandoff();
            var session = CreateSmokeSession();
            ProviderStatus = new ProviderStatusRecord(
                "codex",
                "ready",
                RealExecutionDefault: false,
                UsageMachineReadable: false,
                "mac-worker",
                "Smoke：Mac Worker Codex CLI 已就绪。");
            EligibleHandoffs      = [handoff];
            SelectedHandoff       = handoff;
            RecentSessions        = [session];
            SelectedRecentSession = session;
            SelectedSession       = session;
            SelectedUsageStatus   = "confirmed_available";
        }
    }

    public IReadOnlyList<string> UsageStatusOptions => UsageChoices;

    public ProviderStatusRecord ProviderStatus
    {
        get => _providerStatus;
        private set
        {
            if (SetProperty(ref _providerStatus, value))
            {
                RaisePropertyChanged(nameof(ProviderReadySummary));
                RaiseActionProperties();
            }
        }
    }

    public string ProviderReadySummary =>
        $"Codex：{ProviderStatus.Readiness} · 执行主机：{ProviderStatus.ExecutionHost} · "
        + "Usage 仅人工确认，不抓取余额。";

    public IReadOnlyList<HandoffRecord> EligibleHandoffs
    {
        get => _eligibleHandoffs;
        private set => SetProperty(ref _eligibleHandoffs, value);
    }

    public HandoffRecord? SelectedHandoff
    {
        get => _selectedHandoff;
        set
        {
            if (value is null && _selectedHandoff is not null)
            {
                return;
            }
            if (SetProperty(ref _selectedHandoff, value))
            {
                LatestConfirmation = null;
                RaiseActionProperties();
            }
        }
    }

    public string SelectedUsageStatus
    {
        get => _selectedUsageStatus;
        set
        {
            var normalized = value ?? "unknown";
            if (SetProperty(ref _selectedUsageStatus, normalized))
            {
                RaiseActionProperties();
            }
        }
    }

    public ProviderUsageConfirmationRecord? LatestConfirmation
    {
        get => _latestConfirmation;
        private set
        {
            if (SetProperty(ref _latestConfirmation, value))
            {
                RaisePropertyChanged(nameof(BudgetSummary));
                RaiseActionProperties();
            }
        }
    }

    public string BudgetSummary
    {
        get
        {
            var budget = LatestConfirmation?.Budget ?? ProviderBudgetRecord.Fixed;
            return $"固定预算：{budget.MaxTurns} turns · {budget.TimeoutSeconds} 秒 · "
                + $"最多 {budget.MaxChangedFiles} 文件 · 自动重试 {budget.AutomaticRetries} · "
                + $"网络工具：{(budget.NetworkToolsAllowed ? "允许" : "禁止")}";
        }
    }

    public IReadOnlyList<ProviderSessionRecord> RecentSessions
    {
        get => _recentSessions;
        private set => SetProperty(ref _recentSessions, value);
    }

    public ProviderSessionRecord? SelectedRecentSession
    {
        get => _selectedRecentSession;
        set
        {
            if (value is null && _selectedRecentSession is not null)
            {
                return;
            }
            if (!SetProperty(ref _selectedRecentSession, value))
            {
                return;
            }
            if (value is not null)
            {
                SelectedSession = value;
            }
        }
    }

    public ProviderSessionRecord? SelectedSession
    {
        get => _selectedSession;
        private set
        {
            if (SetProperty(ref _selectedSession, value))
            {
                RaisePropertyChanged(nameof(SessionProgressSummary));
                RaisePropertyChanged(nameof(SafeResultSummary));
                RaiseActionProperties();
            }
        }
    }

    public string SessionProgressSummary => SelectedSession is null
        ? "尚无 Mac Core 创建的 Coding Session。"
        : $"{SelectedSession.Status} · turns {SelectedSession.TurnsUsed}/{SelectedSession.Budget.MaxTurns} · "
          + $"{SelectedSession.ElapsedSeconds}/{SelectedSession.Budget.TimeoutSeconds} 秒 · "
          + $"变更文件 {SelectedSession.ChangedFileCount}/{SelectedSession.Budget.MaxChangedFiles}";

    public string SafeResultSummary => SelectedSession is null
        ? "结果尚未生成。"
        : SelectedSession.ReturnId is null
            ? $"Return：尚未生成 · usage unknown={SelectedSession.ProviderUsageUnknown}"
            : $"Return ID：{SelectedSession.ReturnId} · 仅安全元数据，文件正文仍由本地 Return 验证面板处理。";

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

    public bool CanConfirmUsage =>
        !IsBusy
        && _gateway is not null
        && SelectedHandoff is { Status: "approved", Provider: "codex" }
        && UsageChoices.Contains(SelectedUsageStatus, StringComparer.Ordinal);

    public bool CanCancelSession =>
        !IsBusy
        && _gateway is not null
        && SelectedSession is not null
        && !TerminalStatuses.Contains(SelectedSession.Status);

    public AsyncRelayCommand RefreshCommand { get; }

    public AsyncRelayCommand ConfirmUsageCommand { get; }

    public AsyncRelayCommand CancelSessionCommand { get; }

    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        await RefreshCoreAsync("正在读取 Codex Provider 与 Session 安全事实……", cancellationToken)
            .ConfigureAwait(true);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        await RefreshCoreAsync("正在刷新 Codex Provider 与 Session 状态……", cancellationToken)
            .ConfigureAwait(true);
    }

    public async Task ConfirmUsageAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能提交额度确认。");
        var handoff = SelectedHandoff
            ?? throw new InvalidOperationException("请先选择 approved Codex Handoff。");
        if (!CanConfirmUsage)
        {
            throw new InvalidOperationException("当前状态不能提交额度确认。");
        }

        IsBusy = true;
        StatusMessage = "正在记录人工额度确认；不会读取 Usage 页面或账户余额……";
        try
        {
            var idempotencyKey = $"windows-codex-usage-{handoff.HandoffId}-{Guid.NewGuid():N}";
            LatestConfirmation = await gateway.ConfirmUsageAsync(
                handoff.HandoffId,
                SelectedUsageStatus,
                idempotencyKey,
                cancellationToken).ConfigureAwait(true);
            StatusMessage = LatestConfirmation.Status == "confirmed_available"
                ? "额度人工确认为可用；Mac Core 将依据 Frugal 决策自动推进已选择 Provider，Windows 不启动 Session。"
                : "额度状态不是 confirmed_available；Mac Core 不会启动外部 Coding Session。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CancelSelectedSessionAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能取消真实 Session。");
        var session = SelectedSession
            ?? throw new InvalidOperationException("请先选择一个活动 Session。");
        if (!CanCancelSession)
        {
            throw new InvalidOperationException("当前 Session 已是终态或不可取消。");
        }

        IsBusy = true;
        StatusMessage = "正在请求取消；Mac Worker 将终止完整进程组并强制清理 Session worktree……";
        try
        {
            var idempotencyKey = $"windows-codex-cancel-{session.SessionId}-{Guid.NewGuid():N}";
            var cancelled = await gateway.CancelSessionAsync(
                session.SessionId,
                idempotencyKey,
                cancellationToken).ConfigureAwait(true);
            UpsertAndSelect(cancelled);
            StatusMessage = "取消事实已记录；终态以 Mac Core 返回为准。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCoreAsync(string busyMessage, CancellationToken cancellationToken)
    {
        var gateway = _gateway!;
        IsBusy = true;
        StatusMessage = busyMessage;
        try
        {
            var statusTask   = gateway.GetStatusAsync(cancellationToken);
            var handoffsTask = gateway.GetHandoffsAsync(cancellationToken);
            var sessionsTask = gateway.GetSessionsAsync(cancellationToken);
            await Task.WhenAll(statusTask, handoffsTask, sessionsTask).ConfigureAwait(true);
            ProviderStatus = await statusTask.ConfigureAwait(true);
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            ApplySessions(await sessionsTask.ConfigureAwait(true));
            StatusMessage =
                $"Provider={ProviderStatus.Readiness}；approved Codex Handoff {EligibleHandoffs.Count} 条；Session {RecentSessions.Count} 条。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("刷新失败；已有 Provider 安全投影已保留。", exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplyHandoffs(IReadOnlyList<HandoffRecord> records)
    {
        var selectedId = SelectedHandoff?.HandoffId;
        var eligible = records
            .Where(item =>
                string.Equals(item.Provider, "codex", StringComparison.Ordinal)
                && string.Equals(item.Status, "approved", StringComparison.Ordinal))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        EligibleHandoffs = eligible;
        SelectedHandoff = eligible.FirstOrDefault(item =>
                string.Equals(item.HandoffId, selectedId, StringComparison.Ordinal))
            ?? eligible.FirstOrDefault();
    }

    private void ApplySessions(IReadOnlyList<ProviderSessionRecord> records)
    {
        var selectedId = SelectedSession?.SessionId;
        var ordered = records
            .Where(item => string.Equals(item.Provider, "codex", StringComparison.Ordinal))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        RecentSessions = ordered;
        var refreshed = ordered.FirstOrDefault(item =>
            string.Equals(item.SessionId, selectedId, StringComparison.Ordinal));
        SelectedRecentSession = refreshed ?? ordered.FirstOrDefault();
        if (SelectedRecentSession is null)
        {
            SelectedSession = null;
        }
    }

    private void UpsertAndSelect(ProviderSessionRecord record)
    {
        var records = RecentSessions
            .Where(item => !string.Equals(item.SessionId, record.SessionId, StringComparison.Ordinal))
            .Append(record)
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        RecentSessions        = records;
        SelectedRecentSession = record;
        SelectedSession       = record;
    }

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanConfirmUsage));
        RaisePropertyChanged(nameof(CanCancelSession));
        RefreshCommand.NotifyCanExecuteChanged();
        ConfirmUsageCommand.NotifyCanExecuteChanged();
        CancelSessionCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception)
    {
        StatusMessage = FormatError("Provider 操作失败；已有安全投影已保留。", exception);
    }

    private static bool IsBoundedOperationalError(Exception exception) =>
        exception is ApiException or InvalidOperationException or IOException;

    private static string FormatError(string prefix, Exception exception)
    {
        var message = exception.Message.Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (message.Length > 180)
        {
            message = message[..180] + "…";
        }
        return string.IsNullOrWhiteSpace(message) ? prefix : $"{prefix} {message}";
    }

    private static HandoffRecord CreateSmokeHandoff() => new(
        "handoff-codex-smoke",
        "picotoopet-repo-maintenance-codex-v1",
        "PicotooPet Codex 仓库维护",
        "低预算 Codex 修复",
        "只修改批准范围并返回安全结果。",
        "approved",
        "codex",
        ProviderConfigured: true,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase10d-budgeted-codex-provider-2.3.13.2",
        new string('a', 40),
        "internal",
        6,
        6,
        ["python-regression", "windows-wpf-behavior", "mac-worker-arm64"],
        "8 turns · 900 秒 · 5 文件 · 0 自动重试",
        new string('b', 64),
        new string('c', 64),
        "approval-codex-smoke",
        DateTimeOffset.UtcNow.AddMinutes(-5),
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow.AddMinutes(25),
        ["no push", "no merge", "no automatic retry"]);

    private static ProviderSessionRecord CreateSmokeSession() => new(
        "33333333-3333-3333-3333-333333333333",
        "handoff-codex-smoke",
        "codex",
        "ready_for_review",
        new string('b', 64),
        new string('c', 64),
        ProviderBudgetRecord.Fixed,
        2,
        21,
        1,
        "return-codex-smoke",
        null,
        ProviderUsageUnknown: true,
        DateTimeOffset.UtcNow.AddMinutes(-2),
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow.AddMinutes(-1),
        "Smoke：安全 Return 已就绪，未自动提交或推送。");
}