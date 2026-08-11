using System.Collections.ObjectModel;
using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>2.3.21.1 端到端业务编排控制面；只接受 first-party Adapter 与既有 Work Package。</summary>
public sealed class BusinessPipelinePanelViewModel : ObservableObject
{
    private const string AmazonAnalysisProfile = "reviews.voice_of_customer.v1";
    private const string InspirationAnalysisProfile = "ideas.pattern_analysis.v1";
    private static readonly string[] FixedAdapterProfiles =
    [
        "amazon.reviews_export.v1",
        "inspiration.ideas_export.v1",
    ];

    private readonly ControlCenterSession? _session;
    private readonly BusinessBridgeService? _bridge;
    private readonly ReadOnlyCollection<string> _adapterProfiles = Array.AsReadOnly(FixedAdapterProfiles);
    private IReadOnlyList<BusinessWorkPackageRecord> _workPackages = Array.Empty<BusinessWorkPackageRecord>();
    private IReadOnlyList<BusinessPipelineRunRecord> _runs = Array.Empty<BusinessPipelineRunRecord>();
    private BusinessWorkPackageRecord? _selectedWorkPackage;
    private BusinessPipelineRunRecord? _selectedRun;
    private string _selectedAdapterProfile = FixedAdapterProfiles[0];
    private string _sourcePath = string.Empty;
    private string _projectKey = string.Empty;
    private string _objective = string.Empty;
    private string _statusMessage = "Business Pipeline 由 Mac Core 耐久推进；Windows 只提交 first-party 数据入口与固定控制动作。";
    private bool _isBusy;

    public BusinessPipelinePanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _bridge = new BusinessBridgeService(session);
    }

    private BusinessPipelinePanelViewModel(IReadOnlyList<BusinessPipelineRunRecord> runs)
    {
        Runs = runs;
        SelectedRun = runs.Count > 0 ? runs[0] : null;
    }

    public IReadOnlyList<string> AdapterProfiles => _adapterProfiles;

    public IReadOnlyList<BusinessWorkPackageRecord> WorkPackages
    {
        get => _workPackages;
        private set => SetProperty(ref _workPackages, value);
    }

    public IReadOnlyList<BusinessPipelineRunRecord> Runs
    {
        get => _runs;
        private set => SetProperty(ref _runs, value);
    }

    public BusinessWorkPackageRecord? SelectedWorkPackage
    {
        get => _selectedWorkPackage;
        set
        {
            if (SetProperty(ref _selectedWorkPackage, value))
            {
                if (value is not null)
                {
                    SelectedAdapterProfile = AdapterForAnalysisProfile(value.AnalysisProfile);
                }
                RaiseActions();
            }
        }
    }

    public BusinessPipelineRunRecord? SelectedRun
    {
        get => _selectedRun;
        set
        {
            if (SetProperty(ref _selectedRun, value))
            {
                RaiseActions();
            }
        }
    }

    public string SelectedAdapterProfile
    {
        get => _selectedAdapterProfile;
        set
        {
            if (!FixedAdapterProfiles.Contains(value, StringComparer.Ordinal))
            {
                throw new InvalidOperationException("只允许 first-party Business Adapter profile。");
            }
            if (SetProperty(ref _selectedAdapterProfile, value))
            {
                RaiseActions();
            }
        }
    }

    public string SourcePath
    {
        get => _sourcePath;
        set
        {
            if (SetProperty(ref _sourcePath, value ?? string.Empty))
            {
                RaiseActions();
            }
        }
    }

    public string ProjectKey
    {
        get => _projectKey;
        set
        {
            if (SetProperty(ref _projectKey, value ?? string.Empty))
            {
                RaiseActions();
            }
        }
    }

    public string Objective
    {
        get => _objective;
        set
        {
            if (SetProperty(ref _objective, value ?? string.Empty))
            {
                RaiseActions();
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
                RaiseActions();
            }
        }
    }

    public bool CanSubmitSource =>
        !IsBusy
        && !string.IsNullOrWhiteSpace(SourcePath)
        && !string.IsNullOrWhiteSpace(ProjectKey)
        && !string.IsNullOrWhiteSpace(Objective)
        && _adapterProfiles.Contains(SelectedAdapterProfile, StringComparer.Ordinal);

    public bool CanCreate => !IsBusy && SelectedWorkPackage is not null;

    public bool CanReconcile =>
        !IsBusy && SelectedRun is not null && !IsTerminal(SelectedRun.Status);

    public bool CanCancel =>
        !IsBusy && SelectedRun is not null && !IsTerminal(SelectedRun.Status);

    public bool CanDownloadReturnPackage =>
        !IsBusy
        && SelectedRun is { Status: "Completed", ReturnPackageId: not null };

    public static BusinessPipelinePanelViewModel CreateForSmokeTest(
        IReadOnlyList<BusinessPipelineRunRecord> runs) => new(runs);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            await LoadDataAsync(
                session,
                bridge,
                SelectedWorkPackage?.WorkPackageId,
                SelectedRun?.PipelineRunId,
                cancellationToken).ConfigureAwait(false);
            StatusMessage = $"可编排 Work Package {WorkPackages.Count} 个；Pipeline Run {Runs.Count} 个。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task SubmitSourceAsync(CancellationToken cancellationToken)
    {
        if (!CanSubmitSource)
        {
            throw new InvalidOperationException("请先选择来源文件/目录并填写项目与目标。");
        }
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            var built = await bridge.SubmitAdapterSourceAsync(
                session,
                SelectedAdapterProfile,
                SourcePath,
                ProjectKey,
                Objective,
                cancellationToken).ConfigureAwait(false);
            await LoadDataAsync(
                session,
                bridge,
                built.Manifest.PackageId,
                SelectedRun?.PipelineRunId,
                cancellationToken).ConfigureAwait(false);
            StatusMessage = $"Adapter Work Package 已安全提交：{built.Manifest.PackageId}；可继续创建端到端 Pipeline。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CreateSelectedAsync(CancellationToken cancellationToken)
    {
        var work = SelectedWorkPackage ?? throw new InvalidOperationException("请先选择 Work Package。");
        var expectedAdapter = AdapterForAnalysisProfile(work.AnalysisProfile);
        if (!string.Equals(SelectedAdapterProfile, expectedAdapter, StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Adapter profile 与 Work Package 分析 profile 不匹配。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var created = await session.CreateBusinessPipelineRunAsync(
                new BusinessPipelineRunCreateRequest(
                    work.WorkPackageId,
                    expectedAdapter,
                    BuildIdempotencyKey(work.WorkPackageId, expectedAdapter)),
                cancellationToken).ConfigureAwait(false);
            _ = await session.ReconcileBusinessPipelineRunAsync(created.PipelineRunId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshRunsAsync(session, created.PipelineRunId, cancellationToken).ConfigureAwait(false);
            StatusMessage = "端到端 Pipeline 已创建并提交首次 reconcile；后续由 Mac Core scheduler 耐久推进。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ReconcileSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedRun ?? throw new InvalidOperationException("请先选择 Pipeline Run。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.ReconcileBusinessPipelineRunAsync(selected.PipelineRunId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshRunsAsync(session, selected.PipelineRunId, cancellationToken).ConfigureAwait(false);
            StatusMessage = "已请求一次幂等 reconcile；不会重复创建已绑定的 Creative/Production 子任务。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CancelSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedRun ?? throw new InvalidOperationException("请先选择 Pipeline Run。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.CancelBusinessPipelineRunAsync(selected.PipelineRunId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshRunsAsync(session, selected.PipelineRunId, cancellationToken).ConfigureAwait(false);
            StatusMessage = "Pipeline 已进入取消路径；不会删除来源 Work/Result/Creative/Production Package。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task DownloadSelectedReturnPackageAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedRun ?? throw new InvalidOperationException("请先选择 Pipeline Run。");
        if (!CanDownloadReturnPackage)
        {
            throw new InvalidOperationException("当前 Pipeline 尚无可下载 Return Package。");
        }
        var session = RequireSession();
        var bridge = RequireBridge();
        IsBusy = true;
        try
        {
            var destination = await bridge.DeliverBusinessReturnPackageAsync(
                session,
                selected,
                cancellationToken).ConfigureAwait(false);
            StatusMessage = $"Return Package 已幂等投递到固定 Outbox：{destination}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public string EnsureManagedOutboxPath()
    {
        var bridge = RequireBridge();
        Directory.CreateDirectory(bridge.Outbox);
        return bridge.Outbox;
    }

    private async Task LoadDataAsync(
        ControlCenterSession session,
        BusinessBridgeService bridge,
        string? selectedWorkId,
        string? selectedRunId,
        CancellationToken cancellationToken)
    {
        var workTask = session.GetBusinessWorkPackagesAsync(cancellationToken);
        var runsTask = bridge.SynchronizeBusinessPipelineRunsAsync(session, cancellationToken);
        await Task.WhenAll(workTask, runsTask).ConfigureAwait(false);
        WorkPackages = (await workTask.ConfigureAwait(false))
            .Where(item => item.AnalysisProfile is AmazonAnalysisProfile or InspirationAnalysisProfile)
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        Runs = (await runsTask.ConfigureAwait(false))
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        SelectedWorkPackage = WorkPackages.FirstOrDefault(item => item.WorkPackageId == selectedWorkId)
            ?? (WorkPackages.Count > 0 ? WorkPackages[0] : null);
        SelectedRun = Runs.FirstOrDefault(item => item.PipelineRunId == selectedRunId)
            ?? (Runs.Count > 0 ? Runs[0] : null);
    }

    private async Task RefreshRunsAsync(
        ControlCenterSession session,
        string selectedRunId,
        CancellationToken cancellationToken)
    {
        var bridge = RequireBridge();
        Runs = (await bridge.SynchronizeBusinessPipelineRunsAsync(session, cancellationToken).ConfigureAwait(false))
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        SelectedRun = Runs.FirstOrDefault(item => item.PipelineRunId == selectedRunId)
            ?? (Runs.Count > 0 ? Runs[0] : null);
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanSubmitSource));
        RaisePropertyChanged(nameof(CanCreate));
        RaisePropertyChanged(nameof(CanReconcile));
        RaisePropertyChanged(nameof(CanCancel));
        RaisePropertyChanged(nameof(CanDownloadReturnPackage));
    }

    private static string AdapterForAnalysisProfile(string analysisProfile) => analysisProfile switch
    {
        AmazonAnalysisProfile => "amazon.reviews_export.v1",
        InspirationAnalysisProfile => "inspiration.ideas_export.v1",
        _ => throw new InvalidOperationException("Work Package 不是 2.3.21.1 支持的 first-party business profile。"),
    };

    private static bool IsTerminal(string status) => status is
        "Completed" or "NeedsDeepAI" or "NeedsHuman" or "Rejected" or "Failed" or "Cancelled";

    private static string BuildIdempotencyKey(string workPackageId, string adapterProfile)
    {
        var canonical = $"business-pipeline.v1\n{workPackageId}\n{adapterProfile}";
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)))
            .ToLowerInvariant();
        return $"windows-business-pipeline-{digest}";
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");

    private BusinessBridgeService RequireBridge() =>
        _bridge ?? throw new InvalidOperationException("Smoke test 模式不能写固定 Inbox/Outbox。");
}
