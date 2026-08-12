using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>24.1 Controlled Shadow 控制面；只复现 AcceptedForShadow 信号，不改变运行策略。</summary>
public sealed class QualityShadowPanelViewModel : ObservableObject
{
    private readonly ControlCenterSession? _session;
    private string? _projectKey;
    private IReadOnlyList<QualityImprovementCandidateRecord> _candidates = Array.Empty<QualityImprovementCandidateRecord>();
    private QualityImprovementCandidateRecord? _selectedCandidate;
    private QualityShadowRunRecord? _run;
    private IReadOnlyList<QualityShadowArmMetricRecord> _metrics = Array.Empty<QualityShadowArmMetricRecord>();
    private string _statusMessage = "Shadow 仅重放不可变历史证据；不会执行本地/付费 AI，也不会自动 Promotion。";
    private bool _isBusy;

    public QualityShadowPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private QualityShadowPanelViewModel(
        IReadOnlyList<QualityImprovementCandidateRecord> candidates,
        QualityShadowRunRecord? run,
        IReadOnlyList<QualityShadowArmMetricRecord> metrics)
    {
        _candidates = candidates;
        _selectedCandidate = candidates.Count > 0 ? candidates[0] : null;
        _projectKey = _selectedCandidate?.ProjectKey;
        _run = run;
        _metrics = metrics;
    }

    public string? ProjectKey
    {
        get => _projectKey;
        set
        {
            if (SetProperty(ref _projectKey, value))
            {
                Candidates = Array.Empty<QualityImprovementCandidateRecord>();
                SelectedCandidate = null;
                Run = null;
                Metrics = Array.Empty<QualityShadowArmMetricRecord>();
                RaiseDerived();
            }
        }
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
                Run = null;
                Metrics = Array.Empty<QualityShadowArmMetricRecord>();
                RaiseDerived();
            }
        }
    }

    public QualityShadowRunRecord? Run
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

    public IReadOnlyList<QualityShadowArmMetricRecord> Metrics
    {
        get => _metrics;
        private set => SetProperty(ref _metrics, value);
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
        : $"项目：{ProjectKey} · profile 固定 quality.shadow.v1";

    public string RunText => Run is null
        ? "Shadow：尚未运行。"
        : $"Shadow：{Run.Status} · {Run.Verdict} · report {ShortDigest(Run.ReportDigest)}";

    public bool CanCreate =>
        !IsBusy
        && SelectedCandidate is { Status: "AcceptedForShadow" }
        && Run is null;

    public bool CanReconcile => !IsBusy && Run is not null;

    public bool CanReview => !IsBusy && Run is { Status: "Completed" };

    public bool CanAcceptForPromotionReview => CanReview && Run?.Verdict == "Supported";

    public static QualityShadowPanelViewModel CreateForSmokeTest(
        IReadOnlyList<QualityImprovementCandidateRecord> candidates,
        QualityShadowRunRecord? run,
        IReadOnlyList<QualityShadowArmMetricRecord> metrics) =>
        new(candidates, run, metrics);

    public static QualityShadowPanelViewModel CreateEmptyForSmokeTest() =>
        new(
            Array.Empty<QualityImprovementCandidateRecord>(),
            null,
            Array.Empty<QualityShadowArmMetricRecord>());

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        if (string.IsNullOrWhiteSpace(ProjectKey))
        {
            Candidates = Array.Empty<QualityImprovementCandidateRecord>();
            SelectedCandidate = null;
            Run = null;
            Metrics = Array.Empty<QualityShadowArmMetricRecord>();
            StatusMessage = "选择业务项目后才能查看 AcceptedForShadow 候选。";
            return;
        }

        IsBusy = true;
        try
        {
            var selectedCandidateId = SelectedCandidate?.CandidateId;
            var evaluations = await session.GetQualityEvaluationsAsync(cancellationToken).ConfigureAwait(false);
            var candidateTasks = evaluations
                .Select(item => session.GetQualityImprovementCandidatesAsync(item.EvaluationRunId, cancellationToken))
                .ToArray();
            // Async gate                 Await the aggregate once; never synchronously read Task.Result.
            var candidateGroups = await Task.WhenAll(candidateTasks).ConfigureAwait(false);
            Candidates = candidateGroups
                .SelectMany(items => items)
                .Where(item => item.ProjectKey == ProjectKey && item.Status == "AcceptedForShadow")
                .OrderByDescending(item => item.UpdatedAt)
                .ToArray();
            SelectedCandidate = Candidates.FirstOrDefault(item => item.CandidateId == selectedCandidateId)
                ?? (Candidates.Count > 0 ? Candidates[0] : null);
            await RefreshSelectedRunAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = Candidates.Count == 0
                ? "当前项目没有 AcceptedForShadow 候选；Shadow 不会从 Prepared/Rejected 历史重新激活候选。"
                : $"已加载 {Candidates.Count} 个 AcceptedForShadow 候选；Shadow 只做 deterministic holdout replay。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CreateAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedCandidate ?? throw new InvalidOperationException("请先选择 AcceptedForShadow 候选。");
        if (!CanCreate)
        {
            throw new InvalidOperationException("当前候选不满足 Shadow 创建条件。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            Run = await session.CreateQualityShadowRunAsync(
                new QualityShadowRunCreateRequest(selected.CandidateId),
                cancellationToken).ConfigureAwait(false);
            Metrics = await session.GetQualityShadowMetricsAsync(Run.ShadowRunId, cancellationToken)
                .ConfigureAwait(false);
            StatusMessage = $"Shadow 完成：{Run.Verdict}；0 个本地/付费 AI 调用，未修改候选或运行策略。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ReconcileAsync(CancellationToken cancellationToken)
    {
        var current = Run ?? throw new InvalidOperationException("当前没有 Shadow run。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            Run = await session.ReconcileQualityShadowRunAsync(current.ShadowRunId, cancellationToken)
                .ConfigureAwait(false);
            Metrics = await session.GetQualityShadowMetricsAsync(Run.ShadowRunId, cancellationToken)
                .ConfigureAwait(false);
            StatusMessage = $"Shadow reconcile 完成：{Run.Verdict}；复用同一 run identity。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task MarkReviewedAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Reviewed", cancellationToken);

    public Task AcceptForPromotionReviewAsync(CancellationToken cancellationToken) =>
        ReviewAsync("AcceptedForPromotionReview", cancellationToken);

    public Task RejectAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Rejected", cancellationToken);

    public Task CancelAsync(CancellationToken cancellationToken) =>
        ReviewAsync("Cancelled", cancellationToken);

    private async Task ReviewAsync(string action, CancellationToken cancellationToken)
    {
        var current = Run ?? throw new InvalidOperationException("当前没有 Shadow run。");
        if (!CanReview || (action == "AcceptedForPromotionReview" && !CanAcceptForPromotionReview))
        {
            throw new InvalidOperationException("当前 Shadow run 不允许该审阅动作。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.ReviewQualityShadowRunAsync(
                current.ShadowRunId,
                new QualityShadowReviewRequest(
                    action,
                    $"windows-shadow-review:{current.ShadowRunId}:{action}:v1"),
                cancellationToken).ConfigureAwait(false);
            StatusMessage = action == "AcceptedForPromotionReview"
                ? "已记录 AcceptedForPromotionReview；24.1 仍不会自动 Promotion 或修改生产策略。"
                : $"已记录 Shadow 审阅事实：{action}；未触发任何外部执行。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshSelectedRunAsync(
        ControlCenterSession session,
        CancellationToken cancellationToken)
    {
        if (SelectedCandidate is null)
        {
            Run = null;
            Metrics = Array.Empty<QualityShadowArmMetricRecord>();
            return;
        }
        var runs = await session.GetQualityShadowRunsAsync(
            SelectedCandidate.CandidateId,
            cancellationToken).ConfigureAwait(false);
        Run = runs.Count > 0 ? runs[0] : null;
        Metrics = Run is null
            ? Array.Empty<QualityShadowArmMetricRecord>()
            : await session.GetQualityShadowMetricsAsync(Run.ShadowRunId, cancellationToken)
                .ConfigureAwait(false);
    }

    private void RaiseDerived()
    {
        RaisePropertyChanged(nameof(ProjectText));
        RaisePropertyChanged(nameof(RunText));
        RaisePropertyChanged(nameof(CanCreate));
        RaisePropertyChanged(nameof(CanReconcile));
        RaisePropertyChanged(nameof(CanReview));
        RaisePropertyChanged(nameof(CanAcceptForPromotionReview));
    }

    private static string ShortDigest(string digest) =>
        string.IsNullOrEmpty(digest) ? "-" : $"{digest[..Math.Min(12, digest.Length)]}…";

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");
}
