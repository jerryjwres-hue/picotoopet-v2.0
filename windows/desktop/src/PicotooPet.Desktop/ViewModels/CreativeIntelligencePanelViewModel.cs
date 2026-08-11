using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Creative Intelligence 固定控制面；只选择 PASS 来源与可选业务目标。</summary>
public sealed class CreativeIntelligencePanelViewModel : ObservableObject
{
    public const string FixedCreativeProfile = "creative.content_plan.v1";
    public const string CreativeBoundaryText = "creative_ready != rendered != publish-ready";

    private readonly ControlCenterSession? _session;
    private readonly CreativePackageDeliveryService? _delivery;
    private IReadOnlyList<CreativeSourceSelectionRow> _sources = Array.Empty<CreativeSourceSelectionRow>();
    private IReadOnlyList<CreativeJobRecord> _jobs = Array.Empty<CreativeJobRecord>();
    private CreativeJobRecord? _selectedJob;
    private string? _creativeObjective;
    private string _capabilityStatus = "等待 creative.intelligence.v1 能力快照。";
    private string _statusMessage = "Creative Intelligence 只消费已通过质量门的 Result Package。";
    private bool _isBusy;

    public CreativeIntelligencePanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _delivery = new CreativePackageDeliveryService(session);
    }

    private CreativeIntelligencePanelViewModel(
        IReadOnlyList<CreativeEligibleSourceRecord> sources,
        string capabilityStatus)
    {
        Sources = sources.Select(item => new CreativeSourceSelectionRow(item, OnSelectionChanged)).ToArray();
        CapabilityStatus = capabilityStatus;
    }

    public IReadOnlyList<CreativeSourceSelectionRow> Sources
    {
        get => _sources;
        private set => SetProperty(ref _sources, value);
    }

    public IReadOnlyList<CreativeJobRecord> Jobs
    {
        get => _jobs;
        private set => SetProperty(ref _jobs, value);
    }

    public CreativeJobRecord? SelectedJob
    {
        get => _selectedJob;
        set
        {
            if (SetProperty(ref _selectedJob, value))
            {
                RaiseActions();
            }
        }
    }

    public string? CreativeObjective
    {
        get => _creativeObjective;
        set
        {
            if (value?.Length > 2000)
            {
                throw new ArgumentOutOfRangeException(nameof(value), "Creative Objective 最多 2000 个字符。");
            }
            if (SetProperty(ref _creativeObjective, value))
            {
                RaisePropertyChanged(nameof(ObjectiveCharacterCount));
            }
        }
    }

    public int ObjectiveCharacterCount => CreativeObjective?.Length ?? 0;

    public string CapabilityStatus
    {
        get => _capabilityStatus;
        private set => SetProperty(ref _capabilityStatus, value);
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

    public static string BoundaryText => CreativeBoundaryText;

    public bool CanPrepare
    {
        get
        {
            if (IsBusy)
            {
                return false;
            }
            var selected = Sources.Where(item => item.IsSelected).ToArray();
            return selected.Length is >= 1 and <= 8
                && selected.Select(item => item.ProjectKey).Distinct(StringComparer.Ordinal).Count() == 1;
        }
    }

    public bool CanCancel =>
        !IsBusy
        && SelectedJob is not null
        && SelectedJob.Status is "Ready" or "IdeaRanking" or "BriefGeneration" or "ScriptGeneration" or "ShotPlanning" or "QualityCheck";

    public bool CanExportPackage =>
        !IsBusy
        && SelectedJob is { Status: "creative_ready", CreativePackageId: not null };

    public bool CanExportHandoff =>
        !IsBusy
        && SelectedJob is { Status: "NeedsDeepAI", DeepAiHandoffId: not null };

    public static CreativeIntelligencePanelViewModel CreateForSmokeTest(
        IReadOnlyList<CreativeEligibleSourceRecord> sources,
        string capabilityStatus = "creative.intelligence.v1 · healthy") =>
        new(sources, capabilityStatus);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var selectedSourceIds = Sources.Where(item => item.IsSelected)
                .Select(item => item.ResultPackageId)
                .ToHashSet(StringComparer.Ordinal);
            var selectedJobId = SelectedJob?.CreativeJobId;
            var sourcesTask = session.GetCreativeEligibleSourcesAsync(cancellationToken);
            var jobsTask = session.GetCreativeJobsAsync(cancellationToken);
            var healthTask = session.GetAutomationHealthAsync(cancellationToken);
            await Task.WhenAll(sourcesTask, jobsTask, healthTask).ConfigureAwait(false);
            Sources = (await sourcesTask.ConfigureAwait(false))
                .Select(item => new CreativeSourceSelectionRow(item, OnSelectionChanged)
                {
                    IsSelected = selectedSourceIds.Contains(item.ResultPackageId),
                })
                .ToArray();
            Jobs = await jobsTask.ConfigureAwait(false);
            SelectedJob = Jobs.FirstOrDefault(item => item.CreativeJobId == selectedJobId)
                ?? (Jobs.Count > 0 ? Jobs[0] : null);
            var capability = (await healthTask.ConfigureAwait(false)).Capabilities
                .Where(item => item.Capability == "creative.intelligence.v1")
                .OrderByDescending(item => item.HeartbeatAt)
                .FirstOrDefault();
            CapabilityStatus = capability is null
                ? "creative.intelligence.v1 · 未注册（确认 Mac 本地模型运行状态）"
                : capability.Healthy
                    ? $"creative.intelligence.v1 · healthy · {capability.WorkerId}"
                    : $"creative.intelligence.v1 · unavailable · {capability.WorkerId}";
            StatusMessage = $"可用 PASS Result {Sources.Count} 个；Creative Job {Jobs.Count} 个。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task PrepareAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        var selected = Sources.Where(item => item.IsSelected).ToArray();
        if (selected.Length is < 1 or > 8)
        {
            throw new InvalidOperationException("请选择 1–8 个 PASS Result Package。");
        }
        if (selected.Select(item => item.ProjectKey).Distinct(StringComparer.Ordinal).Count() != 1)
        {
            throw new InvalidOperationException("Creative Job 的 Result Package 必须属于同一个项目。");
        }
        var sourceIds = selected.Select(item => item.ResultPackageId)
            .OrderBy(item => item, StringComparer.Ordinal)
            .ToArray();
        var objective = string.IsNullOrWhiteSpace(CreativeObjective)
            ? null
            : CreativeObjective.Trim();
        var idempotency = BuildIdempotencyKey(sourceIds, objective);
        IsBusy = true;
        try
        {
            var created = await session.CreateCreativeJobAsync(
                new CreativeJobCreateRequest(
                    sourceIds,
                    FixedCreativeProfile,
                    objective,
                    idempotency),
                cancellationToken).ConfigureAwait(false);
            await RefreshAsync(cancellationToken).ConfigureAwait(false);
            SelectedJob = Jobs.FirstOrDefault(item => item.CreativeJobId == created.CreativeJobId)
                ?? created;
            StatusMessage = "Creative Job 已创建；Mac Worker 将按 Idea → Brief → Script → Shot Plan 顺序执行。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CancelSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedJob ?? throw new InvalidOperationException("请先选择 Creative Job。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.CancelCreativeJobAsync(selected.CreativeJobId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshAsync(cancellationToken).ConfigureAwait(false);
            StatusMessage = "Creative Job 已请求取消；不会删除来源 Result Package。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ExportSelectedPackageAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedJob ?? throw new InvalidOperationException("请先选择 Creative Job。");
        var delivery = RequireDelivery();
        IsBusy = true;
        try
        {
            _ = await delivery.DeliverPackageAsync(selected.CreativeJobId, cancellationToken)
                .ConfigureAwait(false);
            StatusMessage = "Creative Package 已幂等导出到固定 BusinessBridge Outbox。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ExportSelectedHandoffAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedJob ?? throw new InvalidOperationException("请先选择 Creative Job。");
        var delivery = RequireDelivery();
        IsBusy = true;
        try
        {
            _ = await delivery.DeliverHandoffAsync(selected.CreativeJobId, cancellationToken)
                .ConfigureAwait(false);
            StatusMessage = "脱敏 Creative Deep-AI Handoff 已导出；系统没有调用任何付费 AI。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void OnSelectionChanged()
    {
        RaisePropertyChanged(nameof(CanPrepare));
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanPrepare));
        RaisePropertyChanged(nameof(CanCancel));
        RaisePropertyChanged(nameof(CanExportPackage));
        RaisePropertyChanged(nameof(CanExportHandoff));
    }

    private static string BuildIdempotencyKey(IEnumerable<string> sourceIds, string? objective)
    {
        var canonical = string.Join("\n", sourceIds) + "\n" + (objective ?? string.Empty);
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)))
            .ToLowerInvariant();
        return $"windows-creative-{digest}";
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");

    private CreativePackageDeliveryService RequireDelivery() =>
        _delivery ?? throw new InvalidOperationException("Smoke test 模式不能写入 Outbox。");
}

/// <summary>一个可选择的 PASS Result Package；只有选择位是 TwoWay 业务状态。</summary>
public sealed class CreativeSourceSelectionRow : ObservableObject
{
    private readonly Action _selectionChanged;
    private bool _isSelected;

    public CreativeSourceSelectionRow(CreativeEligibleSourceRecord source, Action selectionChanged)
    {
        Source = source ?? throw new ArgumentNullException(nameof(source));
        _selectionChanged = selectionChanged ?? throw new ArgumentNullException(nameof(selectionChanged));
    }

    public CreativeEligibleSourceRecord Source { get; }
    public string ResultPackageId => Source.ResultPackageId;
    public string ProjectKey => Source.ProjectKey;
    public string AnalysisProfile => Source.AnalysisProfile;
    public string Summary => Source.Summary;
    public DateTimeOffset CreatedAt => Source.CreatedAt;

    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (SetProperty(ref _isSelected, value))
            {
                _selectionChanged();
            }
        }
    }
}
