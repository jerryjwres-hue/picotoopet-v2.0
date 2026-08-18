using System.Globalization;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>审批中心互斥筛选。</summary>
public enum ApprovalCenterFilter
{
    All,
    Pending,
    Resolved,
    Expired,
}

/// <summary>供 WPF ComboBox 显示的审批筛选项。</summary>
public sealed record ApprovalCenterFilterOption(
    ApprovalCenterFilter Value,
    string Label);

/// <summary>只暴露审批中心允许显示的安全字段。</summary>
public sealed class ApprovalRowViewModel
{
    public ApprovalRowViewModel(ApprovalRecord record)
    {
        Record = record ?? throw new ArgumentNullException(nameof(record));
    }

    public ApprovalRecord Record { get; }
    public string ApprovalId => Record.ApprovalId;
    public string TaskId => Record.TaskId ?? "无关联任务";
    public string ApprovalType => Record.ApprovalType;
    public string ApprovalTypeText => Record.ApprovalType switch
    {
        "cloud_upload" => "云端上传",
        "protected_write" => "受保护写入",
        "release" => "发布操作",
        _ => $"未识别类型 · {Record.ApprovalType}",
    };
    public string ScopeSummary => Record.ScopeSummary;
    public string RequestDigest => Record.RequestDigest;
    public string DigestShort => Record.RequestDigest.Length <= 16
        ? Record.RequestDigest
        : Record.RequestDigest[..16] + "…";
    public string Status => Record.Status;
    public string StatusText => Record.Status switch
    {
        "Pending" => "待处理",
        "Approved" => "已批准",
        "Rejected" => "已拒绝",
        "Expired" => "已过期",
        _ => $"未识别状态 · {Record.Status}",
    };
    public string RequestedAtText => Record.RequestedAt.LocalDateTime.ToString(
        "yyyy-MM-dd HH:mm:ss",
        CultureInfo.InvariantCulture);
    public string ExpiresAtText => Record.ExpiresAt.LocalDateTime.ToString(
        "yyyy-MM-dd HH:mm:ss",
        CultureInfo.InvariantCulture);
    public string ResolvedAtText => Record.ResolvedAt?.LocalDateTime.ToString(
        "yyyy-MM-dd HH:mm:ss",
        CultureInfo.InvariantCulture) ?? "尚未处理";
    public string DecisionReason => string.IsNullOrWhiteSpace(Record.DecisionReason)
        ? "尚无决策原因"
        : Record.DecisionReason;
    public bool IsPending =>
        string.Equals(Status, "Pending", StringComparison.Ordinal)
        && Record.ExpiresAt > DateTimeOffset.UtcNow;
}

/// <summary>审批列表、过期状态、摘要绑定批准/拒绝和重复点击防护。</summary>
public sealed class ApprovalsPageViewModel : PageViewModel
{
    private static readonly IReadOnlyList<ApprovalCenterFilterOption> DefaultFilters =
        new ApprovalCenterFilterOption[]
        {
            new(ApprovalCenterFilter.All, "全部审批"),
            new(ApprovalCenterFilter.Pending, "待处理"),
            new(ApprovalCenterFilter.Resolved, "已处理"),
            new(ApprovalCenterFilter.Expired, "已过期"),
        };

    private readonly ControlCenterSession? _session;
    private readonly IReadOnlyList<ApprovalCenterFilterOption> _filterOptions = DefaultFilters;
    private IReadOnlyList<ApprovalRowViewModel> _allApprovals = Array.Empty<ApprovalRowViewModel>();
    private IReadOnlyList<ApprovalRowViewModel> _visibleApprovals = Array.Empty<ApprovalRowViewModel>();
    private ApprovalCenterFilter _selectedFilter;
    private ApprovalRowViewModel? _selectedApproval;
    private string _decisionReason = string.Empty;
    private string _statusMessage = "审批列表来自 Mac Core；决策将绑定当前请求摘要。";
    private bool _isBusy;
    private bool _isLoaded;

    public ApprovalsPageViewModel(ControlCenterSession session)
        : base("审批")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private ApprovalsPageViewModel(IReadOnlyList<ApprovalRecord> approvals)
        : base("审批")
    {
        ApplyRecords(approvals);
        _isLoaded = true;
    }

    public IReadOnlyList<ApprovalCenterFilterOption> FilterOptions => _filterOptions;

    public IReadOnlyList<ApprovalRowViewModel> AllApprovals
    {
        get => _allApprovals;
        private set => SetProperty(ref _allApprovals, value);
    }

    public IReadOnlyList<ApprovalRowViewModel> VisibleApprovals
    {
        get => _visibleApprovals;
        private set => SetProperty(ref _visibleApprovals, value);
    }

    public ApprovalCenterFilter SelectedFilter
    {
        get => _selectedFilter;
        set
        {
            if (SetProperty(ref _selectedFilter, value))
            {
                ApplyFilter();
            }
        }
    }

    public ApprovalRowViewModel? SelectedApproval
    {
        get => _selectedApproval;
        set
        {
            if (SetProperty(ref _selectedApproval, value))
            {
                DecisionReason = string.Empty;
                RaiseActionProperties();
            }
        }
    }

    public string DecisionReason
    {
        get => _decisionReason;
        set
        {
            if (SetProperty(ref _decisionReason, value))
            {
                RaiseActionProperties();
            }
        }
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

    public bool IsLoaded
    {
        get => _isLoaded;
        private set => SetProperty(ref _isLoaded, value);
    }

    // 操作可用性 --------------------------------------------------------------
    public bool CanRefresh => !IsBusy;
    public bool CanApprove => CanDecide;
    public bool CanReject => CanDecide;

    public string RefreshActionReason => IsBusy
        ? "审批列表正在更新，请稍候。"
        : "从 Mac Core 刷新审批列表。";

    public string ApproveActionReason => BuildDecisionActionReason("批准");
    public string RejectActionReason => BuildDecisionActionReason("拒绝");

    private bool CanDecide =>
        !IsBusy
        && SelectedApproval?.IsPending == true
        && !string.IsNullOrWhiteSpace(DecisionReason);

    public static ApprovalsPageViewModel CreateForSmokeTest(
        IReadOnlyList<ApprovalRecord> approvals) => new(approvals);

    /// <summary>首次打开或用户刷新时读取有界审批快照。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_session is null || IsBusy)
        {
            return;
        }

        IsBusy = true;
        StatusMessage = "正在读取审批列表……";
        try
        {
            var records = await _session.GetApprovalsAsync(cancellationToken).ConfigureAwait(true);
            ApplyRecords(records);
            IsLoaded = true;
            StatusMessage = $"已加载 {records.Length} 项审批；明文令牌和原始路径不会进入页面。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task ApproveSelectedAsync(CancellationToken cancellationToken) =>
        DecideSelectedAsync("approve", "已批准", cancellationToken);

    public Task RejectSelectedAsync(CancellationToken cancellationToken) =>
        DecideSelectedAsync("reject", "已拒绝", cancellationToken);

    private async Task DecideSelectedAsync(
        string decision,
        string successText,
        CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能执行审批动作。");
        var selected = SelectedApproval
            ?? throw new InvalidOperationException("请先选择一项审批。");
        if (!CanDecide)
        {
            throw new InvalidOperationException("只有未过期的待处理审批且填写原因后才能决策。");
        }

        var idempotencyKey = $"windows-approval-{selected.ApprovalId}-{decision}-{Guid.NewGuid():N}";
        var reason = DecisionReason.Trim();
        IsBusy = true;
        StatusMessage = decision == "approve" ? "正在批准……" : "正在拒绝……";
        try
        {
            try
            {
                await session.DecideApprovalAsync(
                    selected.Record,
                    decision,
                    reason,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            catch (ApiException exception) when (exception.Retryable)
            {
                StatusMessage = "网络暂时不可用，正在使用同一幂等键重试一次……";
                await session.DecideApprovalAsync(
                    selected.Record,
                    decision,
                    reason,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }

            var records = await session.GetApprovalsAsync(cancellationToken).ConfigureAwait(true);
            ApplyRecords(records);
            DecisionReason = string.Empty;
            StatusMessage = $"审批{successText}；服务端摘要和终态已重新确认。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplyRecords(IReadOnlyList<ApprovalRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var selectedId = SelectedApproval?.ApprovalId;
        AllApprovals = records
            .OrderByDescending(record => record.RequestedAt)
            .Select(record => new ApprovalRowViewModel(record))
            .ToArray();
        ApplyFilter();
        SelectedApproval = selectedId is null
            ? FirstOrNull(VisibleApprovals)
            : FindById(VisibleApprovals, selectedId) ?? FirstOrNull(VisibleApprovals);
    }

    private void ApplyFilter()
    {
        VisibleApprovals = AllApprovals
            .Where(MatchesFilter)
            .ToArray();
        if (SelectedApproval is not null
            && FindById(VisibleApprovals, SelectedApproval.ApprovalId) is null)
        {
            SelectedApproval = FirstOrNull(VisibleApprovals);
        }
        RaisePropertyChanged(nameof(VisibleApprovals));
    }

    private bool MatchesFilter(ApprovalRowViewModel item) => SelectedFilter switch
    {
        ApprovalCenterFilter.Pending => item.IsPending,
        ApprovalCenterFilter.Resolved => item.Status is "Approved" or "Rejected",
        ApprovalCenterFilter.Expired => item.Status == "Expired",
        _ => true,
    };

    private string BuildDecisionActionReason(string actionLabel)
    {
        if (IsBusy)
        {
            return "审批操作正在处理中，请稍候。";
        }
        if (SelectedApproval is null)
        {
            return "请先选择一项审批。";
        }
        if (!SelectedApproval.IsPending)
        {
            return "该审批已处理、已过期或不再可决策。";
        }
        if (string.IsNullOrWhiteSpace(DecisionReason))
        {
            return "请填写本次决策原因。";
        }
        return $"提交{actionLabel}决策，并绑定当前请求摘要。";
    }

    private static ApprovalRowViewModel? FirstOrNull(
        IReadOnlyList<ApprovalRowViewModel> items) =>
        items.Count == 0 ? null : items[0];

    private static ApprovalRowViewModel? FindById(
        IReadOnlyList<ApprovalRowViewModel> items,
        string approvalId)
    {
        for (var index = 0; index < items.Count; index++)
        {
            if (string.Equals(
                    items[index].ApprovalId,
                    approvalId,
                    StringComparison.Ordinal))
            {
                return items[index];
            }
        }
        return null;
    }

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanRefresh));
        RaisePropertyChanged(nameof(CanApprove));
        RaisePropertyChanged(nameof(CanReject));
        RaisePropertyChanged(nameof(RefreshActionReason));
        RaisePropertyChanged(nameof(ApproveActionReason));
        RaisePropertyChanged(nameof(RejectActionReason));
    }
}
