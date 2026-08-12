using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>25.1 Promotion 治理控制面；只提交 exact approval/rollback 事实，不修改运行策略。</summary>
public sealed class QualityPromotionPanelViewModel : ObservableObject
{
    private readonly IReadOnlyList<string> _fixedRollbackReasons = new[]
    {
        "RegressionObserved",
        "UnexpectedImpact",
        "OperatorDecision",
    };

    private readonly ControlCenterSession? _session;
    private string? _projectKey;
    private IReadOnlyList<QualityShadowRunRecord> _supportedShadows = Array.Empty<QualityShadowRunRecord>();
    private QualityShadowRunRecord? _selectedShadow;
    private IReadOnlyList<QualityPromotionRecord> _promotions = Array.Empty<QualityPromotionRecord>();
    private QualityPromotionRecord? _selectedPromotion;
    private QualityPromotionApprovalRequestRecord? _activationRequest;
    private QualityPromotionApprovalRequestRecord? _rollbackRequest;
    private QualityPromotionHistoryRecord _history = new(
        Array.Empty<QualityPromotionDecisionRecord>(),
        Array.Empty<QualityPromotionRollbackRecord>());
    private string _selectedRollbackReason = "OperatorDecision";
    private string _statusMessage = "Promotion 只记录版本化治理事实；25.1 runtime 不读取 Active 记录来修改生产执行。";
    private bool _isBusy;

    public QualityPromotionPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private QualityPromotionPanelViewModel(
        IReadOnlyList<QualityShadowRunRecord> supportedShadows,
        IReadOnlyList<QualityPromotionRecord> promotions,
        QualityPromotionApprovalRequestRecord? activationRequest,
        QualityPromotionApprovalRequestRecord? rollbackRequest,
        QualityPromotionHistoryRecord history)
    {
        _supportedShadows = supportedShadows;
        _selectedShadow = supportedShadows.Count > 0 ? supportedShadows[0] : null;
        _promotions = promotions;
        _selectedPromotion = promotions.Count > 0 ? promotions[0] : null;
        _projectKey = _selectedPromotion?.ProjectKey ?? _selectedShadow?.ProjectKey;
        _activationRequest = activationRequest;
        _rollbackRequest = rollbackRequest;
        _history = history;
    }

    public string? ProjectKey
    {
        get => _projectKey;
        set
        {
            if (SetProperty(ref _projectKey, value))
            {
                SupportedShadows = Array.Empty<QualityShadowRunRecord>();
                SelectedShadow = null;
                Promotions = Array.Empty<QualityPromotionRecord>();
                SelectedPromotion = null;
                ActivationRequest = null;
                RollbackRequest = null;
                History = EmptyHistory();
                RaiseDerived();
            }
        }
    }

    public IReadOnlyList<QualityShadowRunRecord> SupportedShadows
    {
        get => _supportedShadows;
        private set => SetProperty(ref _supportedShadows, value);
    }

    public QualityShadowRunRecord? SelectedShadow
    {
        get => _selectedShadow;
        set
        {
            if (SetProperty(ref _selectedShadow, value))
            {
                RaiseDerived();
            }
        }
    }

    public IReadOnlyList<QualityPromotionRecord> Promotions
    {
        get => _promotions;
        private set => SetProperty(ref _promotions, value);
    }

    public QualityPromotionRecord? SelectedPromotion
    {
        get => _selectedPromotion;
        set
        {
            if (SetProperty(ref _selectedPromotion, value))
            {
                ActivationRequest = null;
                RollbackRequest = null;
                History = EmptyHistory();
                RaiseDerived();
            }
        }
    }

    public QualityPromotionApprovalRequestRecord? ActivationRequest
    {
        get => _activationRequest;
        private set
        {
            if (SetProperty(ref _activationRequest, value))
            {
                RaiseDerived();
            }
        }
    }

    public QualityPromotionApprovalRequestRecord? RollbackRequest
    {
        get => _rollbackRequest;
        private set
        {
            if (SetProperty(ref _rollbackRequest, value))
            {
                RaiseDerived();
            }
        }
    }

    public QualityPromotionHistoryRecord History
    {
        get => _history;
        private set => SetProperty(ref _history, value);
    }

    public IReadOnlyList<string> RollbackReasons => _fixedRollbackReasons;

    public string SelectedRollbackReason
    {
        get => _selectedRollbackReason;
        set
        {
            if (!_fixedRollbackReasons.Contains(value, StringComparer.Ordinal))
            {
                throw new ArgumentOutOfRangeException(nameof(value), "Rollback reason 必须来自固定枚举。");
            }
            SetProperty(ref _selectedRollbackReason, value);
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

    public string ProjectText => string.IsNullOrWhiteSpace(ProjectKey)
        ? "项目：请先在业务自动化中选择一个项目。"
        : $"项目：{ProjectKey} · profile 固定 quality.promotion.v1";

    public string PromotionText => SelectedPromotion is null
        ? "Promotion：尚未选择版本。"
        : $"Promotion：v{SelectedPromotion.VersionNo} · {SelectedPromotion.Status} · {ShortDigest(SelectedPromotion.ProposalDigest)}";

    public string ApprovalText => ActivationRequest is null
        ? "Activation approval：尚未加载。"
        : $"Activation：{ActivationRequest.Status} · exact {ShortDigest(ActivationRequest.RequestDigest)} · expires {ActivationRequest.ExpiresAt:O}";

    public string RollbackText => RollbackRequest is null
        ? "Rollback approval：尚未申请。"
        : $"Rollback：{RollbackRequest.Status} · {RollbackRequest.RollbackReasonCode} · exact {ShortDigest(RollbackRequest.RequestDigest)}";

    public bool CanCreate => !IsBusy && SelectedShadow is { Status: "Completed", Verdict: "Supported" };

    public bool CanDecideActivation =>
        !IsBusy
        && SelectedPromotion is { Status: "AwaitingApproval" }
        && ActivationRequest is { Status: "Pending" };

    public bool CanRequestRollback => !IsBusy && SelectedPromotion is { Status: "Active" };

    public bool CanDecideRollback =>
        !IsBusy
        && SelectedPromotion is { Status: "Active" }
        && RollbackRequest is { Status: "Pending" };

    public static QualityPromotionPanelViewModel CreateEmptyForSmokeTest() =>
        new(
            Array.Empty<QualityShadowRunRecord>(),
            Array.Empty<QualityPromotionRecord>(),
            null,
            null,
            EmptyHistory());

    public static QualityPromotionPanelViewModel CreateForSmokeTest(
        IReadOnlyList<QualityShadowRunRecord> supportedShadows,
        IReadOnlyList<QualityPromotionRecord> promotions,
        QualityPromotionApprovalRequestRecord? activationRequest,
        QualityPromotionApprovalRequestRecord? rollbackRequest,
        QualityPromotionHistoryRecord history) =>
        new(supportedShadows, promotions, activationRequest, rollbackRequest, history);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        if (string.IsNullOrWhiteSpace(ProjectKey))
        {
            SupportedShadows = Array.Empty<QualityShadowRunRecord>();
            Promotions = Array.Empty<QualityPromotionRecord>();
            SelectedShadow = null;
            SelectedPromotion = null;
            ActivationRequest = null;
            RollbackRequest = null;
            History = EmptyHistory();
            StatusMessage = "选择业务项目后才能查看 Promotion 治理事实。";
            return;
        }

        IsBusy = true;
        try
        {
            var selectedShadowId = SelectedShadow?.ShadowRunId;
            var selectedPromotionId = SelectedPromotion?.PromotionId;
            var shadowsTask = session.GetQualityShadowRunsAsync(null, cancellationToken);
            var promotionsTask = session.GetQualityPromotionsAsync(ProjectKey, null, cancellationToken);
            await Task.WhenAll(shadowsTask, promotionsTask).ConfigureAwait(false);

            SupportedShadows = (await shadowsTask.ConfigureAwait(false))
                .Where(item =>
                    item.ProjectKey == ProjectKey
                    && item.Status == "Completed"
                    && item.Verdict == "Supported")
                .OrderByDescending(item => item.CompletedAt ?? item.CreatedAt)
                .ToArray();
            Promotions = (await promotionsTask.ConfigureAwait(false))
                .OrderByDescending(item => item.VersionNo)
                .ThenByDescending(item => item.CreatedAt)
                .ToArray();

            SelectedShadow = SupportedShadows.FirstOrDefault(item => item.ShadowRunId == selectedShadowId)
                ?? (SupportedShadows.Count > 0 ? SupportedShadows[0] : null);
            SelectedPromotion = Promotions.FirstOrDefault(item => item.PromotionId == selectedPromotionId)
                ?? (Promotions.Count > 0 ? Promotions[0] : null);
            await RefreshSelectedPromotionAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage =
                $"已加载 {SupportedShadows.Count} 个 Supported Shadow、{Promotions.Count} 个 Promotion 版本；Mac Core 仍会强制检查 AcceptedForPromotionReview。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CreateAsync(CancellationToken cancellationToken)
    {
        var shadow = SelectedShadow ?? throw new InvalidOperationException("请先选择 Supported Shadow。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            SelectedPromotion = await session.CreateQualityPromotionAsync(
                new QualityPromotionCreateRequest(shadow.ShadowRunId),
                cancellationToken).ConfigureAwait(false);
            await RefreshListsAndSelectedAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = "Promotion Proposal 已创建；尚未激活，必须使用 Mac Core 返回的 exact request digest 人工决定。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task ApproveActivationAsync(CancellationToken cancellationToken) =>
        DecideActivationAsync("Approved", cancellationToken);

    public Task RejectActivationAsync(CancellationToken cancellationToken) =>
        DecideActivationAsync("Rejected", cancellationToken);

    public Task CancelActivationAsync(CancellationToken cancellationToken) =>
        DecideActivationAsync("Cancelled", cancellationToken);

    public async Task ReconcileAsync(CancellationToken cancellationToken)
    {
        var promotion = SelectedPromotion ?? throw new InvalidOperationException("请先选择 Promotion 版本。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            SelectedPromotion = await session.ReconcileQualityPromotionAsync(
                promotion.PromotionId,
                cancellationToken).ConfigureAwait(false);
            await RefreshListsAndSelectedAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = "Promotion reconcile 完成；未分配新版本，也未改变任何 runtime policy。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task RequestRollbackAsync(CancellationToken cancellationToken)
    {
        var promotion = SelectedPromotion ?? throw new InvalidOperationException("请先选择 Active Promotion。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            RollbackRequest = await session.RequestQualityPromotionRollbackAsync(
                promotion.PromotionId,
                new QualityPromotionRollbackRequest(SelectedRollbackReason),
                cancellationToken).ConfigureAwait(false);
            StatusMessage = "Rollback request 已冻结；仍需 exact digest 人工决定，不会自动回滚。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task ApproveRollbackAsync(CancellationToken cancellationToken) =>
        DecideRollbackAsync("Approved", cancellationToken);

    public Task RejectRollbackAsync(CancellationToken cancellationToken) =>
        DecideRollbackAsync("Rejected", cancellationToken);

    public Task CancelRollbackAsync(CancellationToken cancellationToken) =>
        DecideRollbackAsync("Cancelled", cancellationToken);

    private async Task DecideActivationAsync(string decision, CancellationToken cancellationToken)
    {
        var promotion = SelectedPromotion ?? throw new InvalidOperationException("请先选择 Promotion 版本。");
        var request = ActivationRequest ?? throw new InvalidOperationException("Activation request 尚未加载。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            SelectedPromotion = await session.DecideQualityPromotionActivationAsync(
                promotion.PromotionId,
                new QualityPromotionDecisionRequest(
                    decision,
                    request.RequestDigest,
                    $"windows-promotion-activation:{promotion.PromotionId}:{decision}:v1"),
                cancellationToken).ConfigureAwait(false);
            await RefreshListsAndSelectedAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = decision == "Approved"
                ? "Promotion 已成为 Active 治理事实；25.1 runtime 仍不会读取它来修改执行策略。"
                : $"Activation 已记录 {decision}；未执行任何模型、Provider、ComfyUI 或发布动作。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task DecideRollbackAsync(string decision, CancellationToken cancellationToken)
    {
        var promotion = SelectedPromotion ?? throw new InvalidOperationException("请先选择 Active Promotion。");
        var request = RollbackRequest ?? throw new InvalidOperationException("Rollback request 尚未加载。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            SelectedPromotion = await session.DecideQualityPromotionRollbackAsync(
                promotion.PromotionId,
                new QualityPromotionDecisionRequest(
                    decision,
                    request.RequestDigest,
                    $"windows-promotion-rollback:{promotion.PromotionId}:{decision}:v1"),
                cancellationToken).ConfigureAwait(false);
            await RefreshListsAndSelectedAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = decision == "Approved"
                ? "Rollback 已记录并恢复直接前任治理版本（如存在）；仍未修改 runtime policy。"
                : $"Rollback 已记录 {decision}；当前运行时没有被改变。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshListsAndSelectedAsync(
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        var selectedPromotionId = SelectedPromotion?.PromotionId;
        Promotions = (await session.GetQualityPromotionsAsync(ProjectKey, null, cancellationToken)
                .ConfigureAwait(false))
            .OrderByDescending(item => item.VersionNo)
            .ThenByDescending(item => item.CreatedAt)
            .ToArray();
        SelectedPromotion = Promotions.FirstOrDefault(item => item.PromotionId == selectedPromotionId)
            ?? (Promotions.Count > 0 ? Promotions[0] : null);
        await RefreshSelectedPromotionAsync(session, cancellationToken).ConfigureAwait(false);
    }

    private async Task RefreshSelectedPromotionAsync(
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        if (SelectedPromotion is null)
        {
            ActivationRequest = null;
            RollbackRequest = null;
            History = EmptyHistory();
            return;
        }

        var promotion = SelectedPromotion;
        ActivationRequest = await session.GetQualityPromotionActivationRequestAsync(
            promotion.PromotionId,
            cancellationToken).ConfigureAwait(false);
        History = await session.GetQualityPromotionHistoryAsync(
            promotion.PromotionId,
            cancellationToken).ConfigureAwait(false);

        if (promotion.Status is "Active" or "RolledBack")
        {
            try
            {
                RollbackRequest = await session.GetQualityPromotionRollbackRequestAsync(
                    promotion.PromotionId,
                    cancellationToken).ConfigureAwait(false);
            }
            catch (ApiException exception) when (exception.StatusCode == 404)
            {
                RollbackRequest = null;
            }
        }
        else
        {
            RollbackRequest = null;
        }
    }

    private void RaiseDerived()
    {
        RaisePropertyChanged(nameof(ProjectText));
        RaisePropertyChanged(nameof(PromotionText));
        RaisePropertyChanged(nameof(ApprovalText));
        RaisePropertyChanged(nameof(RollbackText));
        RaisePropertyChanged(nameof(CanCreate));
        RaisePropertyChanged(nameof(CanDecideActivation));
        RaisePropertyChanged(nameof(CanRequestRollback));
        RaisePropertyChanged(nameof(CanDecideRollback));
    }

    private static QualityPromotionHistoryRecord EmptyHistory() =>
        new(Array.Empty<QualityPromotionDecisionRecord>(), Array.Empty<QualityPromotionRollbackRecord>());

    private static string ShortDigest(string digest) =>
        string.IsNullOrEmpty(digest) ? "-" : $"{digest[..Math.Min(12, digest.Length)]}…";

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");
}
