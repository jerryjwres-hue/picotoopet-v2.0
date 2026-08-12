using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Paid-AI 状态/预算/usage/feedback 控制面；不暴露 provider/model/endpoint/key/prompt 执行配置。</summary>
public sealed class DeepAiEscalationPanelViewModel : ObservableObject
{
    private readonly ControlCenterSession? _session;
    private IReadOnlyList<DeepAiEscalationRecord> _escalations = Array.Empty<DeepAiEscalationRecord>();
    private DeepAiEscalationRecord? _selectedEscalation;
    private BusinessWorkPackageRecord? _sourceWorkPackage;
    private DeepAiReadinessRecord? _readiness;
    private DeepAiUsageRecord? _usage;
    private string _statusMessage = "Paid-AI 只接收 Core 已确认的 NEEDS_DEEP_AI 事实；批准不等于自动花钱。";
    private bool _isBusy;

    public DeepAiEscalationPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private DeepAiEscalationPanelViewModel(
        IReadOnlyList<DeepAiEscalationRecord> escalations,
        DeepAiReadinessRecord? readiness,
        DeepAiUsageRecord? usage)
    {
        Escalations = escalations;
        SelectedEscalation = escalations.Count > 0 ? escalations[0] : null;
        _readiness = readiness;
        _usage = usage;
    }

    public IReadOnlyList<DeepAiEscalationRecord> Escalations
    {
        get => _escalations;
        private set => SetProperty(ref _escalations, value);
    }

    public DeepAiEscalationRecord? SelectedEscalation
    {
        get => _selectedEscalation;
        set
        {
            if (SetProperty(ref _selectedEscalation, value))
            {
                _readiness = null;
                _usage = null;
                RaiseDerived();
            }
        }
    }

    public BusinessWorkPackageRecord? SourceWorkPackage
    {
        get => _sourceWorkPackage;
        set
        {
            if (SetProperty(ref _sourceWorkPackage, value))
            {
                RaisePropertyChanged(nameof(CanPrepare));
                RaisePropertyChanged(nameof(SourceText));
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
                RaiseDerived();
            }
        }
    }

    public string SourceText => SourceWorkPackage is null
        ? "来源：选择一个 NeedsDeepAI 业务包后可准备升级审批。"
        : $"来源：{SourceWorkPackage.ProjectKey} · {SourceWorkPackage.WorkPackageId} · {SourceWorkPackage.Status}";

    public string ExecutionReadinessText
    {
        get
        {
            if (SelectedEscalation is null)
            {
                return "执行未启用 · 尚未选择 escalation。";
            }
            if (_readiness is null)
            {
                return "执行状态：等待 Core readiness。";
            }
            if (!_readiness.ExecutionEnabled)
            {
                return "执行未启用 · 批准后仍不会自动调用付费 Provider；Manual Handoff 保留。";
            }
            return _readiness.ProviderReady
                ? "执行已启用 · ProviderReady；仍受冻结预算/调用次数限制。"
                : $"执行已启用但尚未 ProviderReady · {_readiness.ReasonCode}";
        }
    }

    public string BudgetText => SelectedEscalation is null
        ? "预算：尚未选择 escalation。"
        : $"冻结预算：${SelectedEscalation.MaxCostUsd:F2} total · 最多 {SelectedEscalation.MaxCalls} calls · input ≤ {SelectedEscalation.MaxInputTokens} · output ≤ {SelectedEscalation.MaxOutputTokens}";

    public string UsageText => _usage is null
        ? "实际使用：等待 Core usage。"
        : $"实际使用：{_usage.CallsUsed} calls · input {_usage.InputTokens} · output {_usage.OutputTokens} · ${_usage.CostUsd:F6}";

    public string ApprovalText => SelectedEscalation?.ApprovalId is { Length: > 0 } approvalId
        ? $"审批：{approvalId} · 请在现有审批中心决定；这里不能改 Provider/Model/Budget。"
        : "审批：尚未创建。";

    public string ManualHandoffText => _readiness?.ManualHandoffId is { Length: > 0 } handoffId
        ? $"Manual Handoff：{handoffId}（Paid-AI 不可用时仍可继续人工路径）"
        : "Manual Handoff：等待 Core readiness。";

    public string ProviderFactText => SelectedEscalation is null
        ? "Provider/Profile：由 Core trusted policy 冻结。"
        : $"冻结 Provider：{SelectedEscalation.ProviderProfileId} · Model：{SelectedEscalation.ModelId}";

    public bool CanPrepare =>
        !IsBusy
        && SourceWorkPackage is { Status: "NeedsDeepAI", DeepAiHandoffId: not null };

    public bool CanReconcile => !IsBusy && SelectedEscalation is not null;

    public bool CanFeedback =>
        !IsBusy
        && SelectedEscalation is { Status: "Completed" or "NeedsHuman" or "Rejected" };

    public static DeepAiEscalationPanelViewModel CreateForSmokeTest(
        IReadOnlyList<DeepAiEscalationRecord>? escalations = null,
        DeepAiReadinessRecord? readiness = null,
        DeepAiUsageRecord? usage = null) =>
        new(
            escalations ?? Array.Empty<DeepAiEscalationRecord>(),
            readiness,
            usage);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var selectedId = SelectedEscalation?.EscalationJobId;
            Escalations = await session.GetDeepAiEscalationsAsync(cancellationToken).ConfigureAwait(false);
            SelectedEscalation = Escalations.FirstOrDefault(item => item.EscalationJobId == selectedId)
                ?? (Escalations.Count > 0 ? Escalations[0] : null);
            await RefreshSelectedFactsAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = $"已加载 {Escalations.Count} 个 Deep-AI escalation；刷新本身不会触发付费调用。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task PrepareSelectedSourceAsync(CancellationToken cancellationToken)
    {
        var source = SourceWorkPackage
            ?? throw new InvalidOperationException("请先选择一个 NeedsDeepAI 业务包。");
        if (!CanPrepare)
        {
            throw new InvalidOperationException("只有 Core 已确认 NeedsDeepAI 且存在 Handoff 的业务包可准备 Paid-AI 审批。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var created = await session.PrepareDeepAiEscalationAsync(
                new DeepAiEscalationPrepareRequest(
                    "business.local_intelligence",
                    source.WorkPackageId),
                cancellationToken).ConfigureAwait(false);
            Escalations = await session.GetDeepAiEscalationsAsync(cancellationToken).ConfigureAwait(false);
            SelectedEscalation = Escalations.FirstOrDefault(item => item.EscalationJobId == created.EscalationJobId)
                ?? created;
            await RefreshSelectedFactsAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = "Paid-AI escalation 已准备并绑定精确审批；当前操作没有调用 Provider，也没有产生费用。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ReconcileSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedEscalation
            ?? throw new InvalidOperationException("请先选择 Deep-AI escalation。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var updated = await session.ReconcileDeepAiEscalationAsync(
                selected.EscalationJobId,
                cancellationToken).ConfigureAwait(false);
            ReplaceSelected(updated);
            await RefreshSelectedFactsAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = "已按 Core durable facts 重新对齐状态；reconcile 不会自行提高预算或切换 Provider。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task RecordAcceptedAsync(CancellationToken cancellationToken) =>
        RecordFeedbackAsync("Accepted", ["accepted", "windows-control-center"], cancellationToken);

    public Task RecordRejectedAsync(CancellationToken cancellationToken) =>
        RecordFeedbackAsync("Rejected", ["rejected", "windows-control-center"], cancellationToken);

    public Task RecordModifiedAsync(CancellationToken cancellationToken) =>
        RecordFeedbackAsync("Modified", ["modified", "windows-control-center"], cancellationToken);

    private async Task RecordFeedbackAsync(
        string action,
        string[] reasonTags,
        CancellationToken cancellationToken)
    {
        var selected = SelectedEscalation
            ?? throw new InvalidOperationException("请先选择 Deep-AI escalation。");
        if (!CanFeedback)
        {
            throw new InvalidOperationException("只有已完成/NeedsHuman/Rejected escalation 可记录人工反馈。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var identity = selected.AcceptedResultDigest ?? selected.SanitizedPackageDigest;
            _ = await session.RecordDeepAiFeedbackAsync(
                selected.EscalationJobId,
                new DeepAiFeedbackRequest(
                    action,
                    reasonTags,
                    selected.AcceptedResultDigest,
                    selected.AcceptedResultRelpath,
                    $"windows-feedback:{selected.EscalationJobId}:{action}:{identity}"),
                cancellationToken).ConfigureAwait(false);
            StatusMessage = $"已记录 {action} Quality Learning 事实；反馈不会触发新付费调用，也不会改变 Provider/Model/Budget。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshSelectedFactsAsync(
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        if (SelectedEscalation is null)
        {
            _readiness = null;
            _usage = null;
            RaiseDerived();
            return;
        }
        var readinessTask = session.GetDeepAiReadinessAsync(
            SelectedEscalation.EscalationJobId,
            cancellationToken);
        var usageTask = session.GetDeepAiUsageAsync(
            SelectedEscalation.EscalationJobId,
            cancellationToken);
        await Task.WhenAll(readinessTask, usageTask).ConfigureAwait(false);
        _readiness = await readinessTask.ConfigureAwait(false);
        _usage = await usageTask.ConfigureAwait(false);
        RaiseDerived();
    }

    private void ReplaceSelected(DeepAiEscalationRecord updated)
    {
        Escalations = Escalations
            .Select(item => item.EscalationJobId == updated.EscalationJobId ? updated : item)
            .ToArray();
        SelectedEscalation = updated;
    }

    private void RaiseDerived()
    {
        RaisePropertyChanged(nameof(ExecutionReadinessText));
        RaisePropertyChanged(nameof(BudgetText));
        RaisePropertyChanged(nameof(UsageText));
        RaisePropertyChanged(nameof(ApprovalText));
        RaisePropertyChanged(nameof(ManualHandoffText));
        RaisePropertyChanged(nameof(ProviderFactText));
        RaisePropertyChanged(nameof(CanPrepare));
        RaisePropertyChanged(nameof(CanReconcile));
        RaisePropertyChanged(nameof(CanFeedback));
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");
}
