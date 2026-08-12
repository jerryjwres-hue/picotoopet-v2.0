using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>23.1 离线质量评估控制面；只管理 snapshot/evaluation/candidate review 事实，不改变运行策略。</summary>
public sealed class QualityEvaluationPanelViewModel : ObservableObject
{
    private readonly ControlCenterSession? _session;
    private string? _projectKey;
    private QualityEvaluationSnapshotRecord? _snapshot;
    private QualityEvaluationRunRecord? _run;
    private IReadOnlyList<QualityEvaluationMetricRecord> _metrics = Array.Empty<QualityEvaluationMetricRecord>();
    private IReadOnlyList<QualityImprovementCandidateRecord> _candidates = Array.Empty<QualityImprovementCandidateRecord>();
    private QualityImprovementCandidateRecord? _selectedCandidate;
    private string _statusMessage = "质量评估只读取 Quality Learning 事实；不会自动修改任何运行策略。";
    private bool _isBusy;

    public QualityEvaluationPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private QualityEvaluationPanelViewModel(
        QualityEvaluationSnapshotRecord? snapshot,
        QualityEvaluationRunRecord? run,
        IReadOnlyList<QualityEvaluationMetricRecord> metrics,
        IReadOnlyList<QualityImprovementCandidateRecord> candidates)
    {
        _snapshot = snapshot;
        _run = run;
        _projectKey = snapshot?.ProjectKey;
        _metrics = metrics;
        _candidates = candidates;
        _selectedCandidate = candidates.Count > 0 ? candidates[0] : null;
    }

    public string? ProjectKey
    {
        get => _projectKey;
        set
        {
            if (SetProperty(ref _projectKey, value))
            {
                // Scope change              Discard only the local projection; durable Core facts remain intact.
                _snapshot = null;
                _run = null;
                _metrics = Array.Empty<QualityEvaluationMetricRecord>();
                _candidates = Array.Empty<QualityImprovementCandidateRecord>();
                _selectedCandidate = null;
                RaiseDerived();
            }
        }
    }

    public QualityEvaluationSnapshotRecord? Snapshot
    {
        get => _snapshot;
        private set
        {
            if (SetProperty(ref _snapshot, value))
            {
                RaiseDerived();
            }
        }
    }

    public QualityEvaluationRunRecord? Run
    {
        get => _run;
        private set
        {
            if (SetProperty(ref _run, value))
            {
                RaiseDerived();
            }
        }
    }

    public IReadOnlyList<QualityEvaluationMetricRecord> Metrics
    {
        get => _metrics;
        private set => SetProperty(ref _metrics, value);
    }

    public IReadOnlyList<QualityImprovementCandidateRecord> Candidates
    {
        get => _candidates;
        private set => SetProperty(ref _candidates, value);
    }

    public QualityImprovementCandidateRecord? SelectedCandidate
    {
        get => _selectedCandidate;
        set
        {
            if (SetProperty(ref _selectedCandidate, value))
            {
                RaiseDerived();
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

    public string ProjectText => string.IsNullOrWhiteSpace(ProjectKey)
        ? "项目：请先在业务自动化中选择一个项目。"
        : $"项目：{ProjectKey} · profile 固定 quality.offline.v1";

    public string SnapshotText => Snapshot is null
        ? "Snapshot：尚未创建。"
        : $"Snapshot：{Snapshot.SnapshotId} · {Snapshot.MemberCount} facts · {Snapshot.SnapshotDigest[..Math.Min(12, Snapshot.SnapshotDigest.Length)]}…";

    public string RunText => Run is null
        ? "Evaluation：尚未运行。"
        : $"Evaluation：{Run.Status} · {Run.EvaluationRunId} · report {Run.ReportDigest[..Math.Min(12, Run.ReportDigest.Length)]}…";

    public bool CanCreate => !IsBusy && !string.IsNullOrWhiteSpace(ProjectKey);

    public bool CanEvaluate => !IsBusy && Snapshot is not null;

    public bool CanReview =>
        !IsBusy
        && SelectedCandidate is { Status: "Prepared" or "Reviewed" };

    public static QualityEvaluationPanelViewModel CreateForSmokeTest(
        QualityEvaluationSnapshotRecord snapshot,
        QualityEvaluationRunRecord run,
        IReadOnlyList<QualityEvaluationMetricRecord> metrics,
        IReadOnlyList<QualityImprovementCandidateRecord> candidates) =>
        new(snapshot, run, metrics, candidates);

    public static QualityEvaluationPanelViewModel CreateEmptyForSmokeTest() =>
        new(
            null,
            null,
            Array.Empty<QualityEvaluationMetricRecord>(),
            Array.Empty<QualityImprovementCandidateRecord>());

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        if (string.IsNullOrWhiteSpace(ProjectKey))
        {
            Snapshot = null;
            Run = null;
            Metrics = Array.Empty<QualityEvaluationMetricRecord>();
            Candidates = Array.Empty<QualityImprovementCandidateRecord>();
            SelectedCandidate = null;
            StatusMessage = "选择业务项目后才能查看该项目的离线质量评估。";
            return;
        }

        IsBusy = true;
        try
        {
            var selectedCandidateId = SelectedCandidate?.CandidateId;
            var snapshots = await session.GetQualityEvaluationSnapshotsAsync(ProjectKey, cancellationToken)
                .ConfigureAwait(false);
            // Analyzer gate             IReadOnlyList is indexable; avoid LINQ FirstOrDefault (CA1826).
            Snapshot = snapshots.Count > 0 ? snapshots[0] : null;
            if (Snapshot is null)
            {
                Run = null;
                Metrics = Array.Empty<QualityEvaluationMetricRecord>();
                Candidates = Array.Empty<QualityImprovementCandidateRecord>();
                SelectedCandidate = null;
                StatusMessage = "当前项目尚无 Evaluation Snapshot；刷新不会执行 AI，也不会产生费用。";
                return;
            }

            var runs = await session.GetQualityEvaluationsAsync(cancellationToken).ConfigureAwait(false);
            Run = runs.FirstOrDefault(item => item.SnapshotId == Snapshot.SnapshotId);
            if (Run is null)
            {
                Metrics = Array.Empty<QualityEvaluationMetricRecord>();
                Candidates = Array.Empty<QualityImprovementCandidateRecord>();
                SelectedCandidate = null;
                StatusMessage = "已找到 Snapshot，尚未运行 deterministic offline evaluation。";
                return;
            }

            await RefreshRunFactsAsync(session, selectedCandidateId, cancellationToken).ConfigureAwait(false);
            StatusMessage = $"已加载 {Metrics.Count} 个 metric facts 和 {Candidates.Count} 个 Improvement Candidates；仅供审阅。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CreateSnapshotAsync(CancellationToken cancellationToken)
    {
        if (!CanCreate)
        {
            throw new InvalidOperationException("请先选择一个业务项目。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            Snapshot = await session.CreateQualityEvaluationSnapshotAsync(
                new QualityEvaluationSnapshotCreateRequest(
                    ProjectKey!,
                    "quality.offline.v1",
                    null,
                    null,
                    null,
                    10000),
                cancellationToken).ConfigureAwait(false);
            Run = null;
            Metrics = Array.Empty<QualityEvaluationMetricRecord>();
            Candidates = Array.Empty<QualityImprovementCandidateRecord>();
            SelectedCandidate = null;
            StatusMessage = $"已冻结 {Snapshot.MemberCount} 条 Quality Learning facts；未调用本地或付费 AI。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task EvaluateAsync(CancellationToken cancellationToken)
    {
        var snapshot = Snapshot ?? throw new InvalidOperationException("请先创建 Evaluation Snapshot。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            Run = await session.CreateQualityEvaluationAsync(
                new QualityEvaluationRunCreateRequest(snapshot.SnapshotId),
                cancellationToken).ConfigureAwait(false);
            await RefreshRunFactsAsync(session, null, cancellationToken).ConfigureAwait(false);
            StatusMessage = $"离线评估完成：{Candidates.Count} 个候选；不会自动修改任何运行策略。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task MarkReviewedAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Reviewed", cancellationToken);

    public Task AcceptForShadowAsync(CancellationToken cancellationToken) =>
        ReviewAsync("AcceptedForShadow", cancellationToken);

    public Task RejectAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Rejected", cancellationToken);

    public Task CancelAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Cancelled", cancellationToken);

    private async Task ReviewAsync(string action, CancellationToken cancellationToken)
    {
        var selected = SelectedCandidate ?? throw new InvalidOperationException("请先选择 Improvement Candidate。");
        if (!CanReview)
        {
            throw new InvalidOperationException("当前候选已进入终态，不能再次改变审阅结论。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.ReviewQualityImprovementCandidateAsync(
                selected.CandidateId,
                new QualityImprovementCandidateReviewRequest(
                    action,
                    $"windows-quality-review:{selected.CandidateId}:{action}:v1"),
                cancellationToken).ConfigureAwait(false);
            var selectedId = selected.CandidateId;
            await RefreshRunFactsAsync(session, selectedId, cancellationToken).ConfigureAwait(false);
            StatusMessage = action == "AcceptedForShadow"
                ? "已记录 AcceptedForShadow；23.1 不执行 Shadow/A-B，也不会应用策略。"
                : $"已记录候选审阅事实：{action}；没有执行 AI 或策略变更。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshRunFactsAsync(
        ControlCenterSession session,
        string? selectedCandidateId,
        CancellationToken cancellationToken)
    {
        if (Run is null)
        {
            return;
        }
        var metricsTask = session.GetQualityEvaluationMetricsAsync(
            Run.EvaluationRunId,
            cancellationToken);
        var candidatesTask = session.GetQualityImprovementCandidatesAsync(
            Run.EvaluationRunId,
            cancellationToken);
        await Task.WhenAll(metricsTask, candidatesTask).ConfigureAwait(false);
        Metrics = await metricsTask.ConfigureAwait(false);
        Candidates = await candidatesTask.ConfigureAwait(false);
        SelectedCandidate = Candidates.FirstOrDefault(item => item.CandidateId == selectedCandidateId)
            ?? (Candidates.Count > 0 ? Candidates[0] : null);
    }

    private void RaiseDerived()
    {
        RaisePropertyChanged(nameof(ProjectText));
        RaisePropertyChanged(nameof(SnapshotText));
        RaisePropertyChanged(nameof(RunText));
        RaisePropertyChanged(nameof(CanCreate));
        RaisePropertyChanged(nameof(CanEvaluate));
        RaisePropertyChanged(nameof(CanReview));
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");
}
