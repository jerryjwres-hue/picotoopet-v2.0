using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>业务自动化事实页；固定 Inbox/Outbox + Mac 本地智能，不暴露模型/prompt/命令输入。</summary>
public sealed class BusinessAutomationPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private readonly BusinessBridgeService? _bridge;
    private IReadOnlyList<BusinessWorkPackageRecord> _packages = Array.Empty<BusinessWorkPackageRecord>();
    private BusinessWorkPackageRecord? _selectedPackage;
    private string _localIntelligenceStatus = "等待 Mac 本地智能能力快照。";
    private string _statusMessage = "业务 Work Package 与 Result Package 事实来自 Mac Core。";
    private bool _isBusy;

    public BusinessAutomationPageViewModel(ControlCenterSession session) : base("业务自动化")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _bridge = new BusinessBridgeService(session);
        Creative = new CreativeIntelligencePanelViewModel(session);
    }

    private BusinessAutomationPageViewModel(
        IReadOnlyList<BusinessWorkPackageRecord> packages,
        string localIntelligenceStatus) : base("业务自动化")
    {
        Packages = packages;
        SelectedPackage = packages.Count > 0 ? packages[0] : null;
        LocalIntelligenceStatus = localIntelligenceStatus;
        Creative = CreativeIntelligencePanelViewModel.CreateForSmokeTest(
            Array.Empty<CreativeEligibleSourceRecord>(),
            "creative.intelligence.v1 · smoke");
    }

    public CreativeIntelligencePanelViewModel Creative { get; }

    public IReadOnlyList<BusinessWorkPackageRecord> Packages
    {
        get => _packages;
        private set => SetProperty(ref _packages, value);
    }

    public BusinessWorkPackageRecord? SelectedPackage
    {
        get => _selectedPackage;
        set
        {
            if (SetProperty(ref _selectedPackage, value))
            {
                RaiseActions();
            }
        }
    }

    public string LocalIntelligenceStatus
    {
        get => _localIntelligenceStatus;
        private set => SetProperty(ref _localIntelligenceStatus, value);
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
                RaiseActions();
            }
        }
    }

    public bool CanCancel => !IsBusy && SelectedPackage?.Status is
        "Receiving" or "Validating" or "Ready" or "Preprocessing" or "LocalInference" or "QualityCheck";

    public bool CanExportDeepAiHandoff =>
        !IsBusy
        && SelectedPackage is { Status: "NeedsDeepAI", DeepAiHandoffId: not null };

    public bool CanDeliverResult =>
        !IsBusy
        && SelectedPackage is { Status: "Completed", ResultPackageId: not null };

    public static BusinessAutomationPageViewModel CreateForSmokeTest(
        IReadOnlyList<BusinessWorkPackageRecord> packages,
        string localIntelligenceStatus = "local.intelligence.v1 · healthy") =>
        new(packages, localIntelligenceStatus);

    /// <summary>刷新时顺带消费固定 Inbox 并投递已完成 Result；没有自由路径或模型参数。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            var bridgeResult = await bridge.ProcessInboxAsync(cancellationToken).ConfigureAwait(false);
            var delivered = await bridge.DeliverCompletedResultsAsync(cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage =
                $"已加载 {Packages.Count} 个业务包；Inbox 提交 {bridgeResult.Submitted}，隔离 {bridgeResult.Quarantined}，暂缓 {bridgeResult.Deferred}；Result 投递 {delivered}。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task SubmitInboxAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            var result = await bridge.ProcessInboxAsync(cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = $"Inbox：提交 {result.Submitted}，隔离 {result.Quarantined}，暂缓 {result.Deferred}。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task DeliverResultsAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            var delivered = await bridge.DeliverCompletedResultsAsync(cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = $"已向固定 Outbox 幂等投递 {delivered} 个新 Result Package。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CancelSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedPackage ?? throw new InvalidOperationException("请先选择业务包。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            await session.CancelBusinessWorkPackageAsync(selected.WorkPackageId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            SelectedPackage = Packages.FirstOrDefault(item => item.WorkPackageId == selected.WorkPackageId);
            StatusMessage = "业务包已进入 Cancelled；不会删除原业务程序文件。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ExportSelectedDeepAiHandoffAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedPackage ?? throw new InvalidOperationException("请先选择业务包。");
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            _ = await bridge.ExportDeepAiHandoffAsync(selected.WorkPackageId, cancellationToken)
                .ConfigureAwait(false);
            StatusMessage = "已把脱敏 Deep-AI Handoff 导出到固定 Outbox；系统没有调用任何付费 AI。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCoreAsync(
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        var selectedId = SelectedPackage?.WorkPackageId;
        var packagesTask = session.GetBusinessWorkPackagesAsync(cancellationToken);
        var healthTask = session.GetAutomationHealthAsync(cancellationToken);
        await Task.WhenAll(packagesTask, healthTask).ConfigureAwait(false);
        Packages = await packagesTask.ConfigureAwait(false);
        SelectedPackage = Packages.FirstOrDefault(item => item.WorkPackageId == selectedId)
            ?? (Packages.Count > 0 ? Packages[0] : null);
        var local = (await healthTask.ConfigureAwait(false)).Capabilities
            .Where(item => item.Capability == "local.intelligence.v1")
            .OrderByDescending(item => item.HeartbeatAt)
            .FirstOrDefault();
        LocalIntelligenceStatus = local is null
            ? "local.intelligence.v1 · 未注册（确认 Mac 本地模型运行状态）"
            : local.Healthy
                ? $"local.intelligence.v1 · healthy · {local.WorkerId}"
                : $"local.intelligence.v1 · unavailable · {local.WorkerId}";
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanCancel));
        RaisePropertyChanged(nameof(CanExportDeepAiHandoff));
        RaisePropertyChanged(nameof(CanDeliverResult));
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");

    private BusinessBridgeService RequireBridge() =>
        _bridge ?? throw new InvalidOperationException("Smoke test 模式不能访问本地 Inbox/Outbox。");
}
