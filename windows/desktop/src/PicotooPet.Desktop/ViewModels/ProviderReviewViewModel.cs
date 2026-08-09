using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 10D/E Review、Adoption、Commit 与受控远端 Publication 状态。</summary>
public sealed class ProviderReviewViewModel : ObservableObject
{
    private readonly IProviderReviewGateway? _gateway;
    private IReadOnlyList<ProviderSessionRecord> _reviewableSessions = [];
    private ProviderSessionRecord? _selectedSession;
    private ProviderReviewRecord? _review;
    private IReadOnlyList<ProviderAdoptionCandidateRecord> _candidates = [];
    private ProviderAdoptionCandidateRecord? _selectedCandidate;
    private IReadOnlyList<ProviderCommitCandidateRecord> _commitCandidates = [];
    private ProviderCommitCandidateRecord? _selectedCommitCandidate;
    private IReadOnlyList<ProviderPublicationCandidateRecord> _publicationCandidates = [];
    private ProviderPublicationCandidateRecord? _selectedPublicationCandidate;
    private string _statusMessage = "Review、本地提交与远端发布均受控；任何外部写都需要新的明确审批。";
    private bool _isBusy;

    public ProviderReviewViewModel()
        : this(null, initializeSmoke: true)
    {
    }

    public ProviderReviewViewModel(IProviderReviewGateway gateway)
        : this(gateway ?? throw new ArgumentNullException(nameof(gateway)), initializeSmoke: false)
    {
    }

    private ProviderReviewViewModel(IProviderReviewGateway? gateway, bool initializeSmoke)
    {
        _gateway = gateway;
        RefreshCommand = new AsyncRelayCommand(
            () => LoadAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy);
        AcceptCommand = new AsyncRelayCommand(
            () => AcceptAsync(CancellationToken.None),
            HandleCommandError,
            () => CanAccept);
        RejectCommand = new AsyncRelayCommand(
            () => RejectAsync(CancellationToken.None),
            HandleCommandError,
            () => CanReject);
        RefreshCandidateCommand = new AsyncRelayCommand(
            () => RefreshCandidateAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy && Review?.CandidateId is not null);
        PrepareCommitCommand = new AsyncRelayCommand(
            () => PrepareCommitAsync(CancellationToken.None),
            HandleCommandError,
            () => CanPrepareCommit);
        RefreshCommitCommand = new AsyncRelayCommand(
            () => RefreshCommitAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy && SelectedCandidate is not null);
        PreparePublicationCommand = new AsyncRelayCommand(
            () => PreparePublicationAsync(CancellationToken.None),
            HandleCommandError,
            () => CanPreparePublication);
        RefreshPublicationCommand = new AsyncRelayCommand(
            () => RefreshPublicationAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy && SelectedCommitCandidate is not null);

        if (initializeSmoke)
        {
            var session = SmokeSession();
            ReviewableSessions = [session];
            SelectedSession = session;
            Review = SmokeReview(session.SessionId);
            Candidates = [SmokeCandidate(session.SessionId)];
            SelectedCandidate = Candidates[0];
            CommitCandidates = [SmokeCommitCandidate(session.SessionId, SelectedCandidate.CandidateId)];
            SelectedCommitCandidate = CommitCandidates[0];
            PublicationCandidates = [SmokePublicationCandidate(session.SessionId, SelectedCommitCandidate.CommitCandidateId)];
            SelectedPublicationCandidate = PublicationCandidates[0];
        }
    }

    public IReadOnlyList<ProviderSessionRecord> ReviewableSessions
    {
        get => _reviewableSessions;
        private set => SetProperty(ref _reviewableSessions, value);
    }

    public ProviderSessionRecord? SelectedSession
    {
        get => _selectedSession;
        set
        {
            if (SetProperty(ref _selectedSession, value))
            {
                RaiseActions();
            }
        }
    }

    public ProviderReviewRecord? Review
    {
        get => _review;
        private set
        {
            if (SetProperty(ref _review, value))
            {
                RaisePropertyChanged(nameof(ReviewSummary));
                RaiseActions();
            }
        }
    }

    public IReadOnlyList<ProviderAdoptionCandidateRecord> Candidates
    {
        get => _candidates;
        private set => SetProperty(ref _candidates, value);
    }

    public ProviderAdoptionCandidateRecord? SelectedCandidate
    {
        get => _selectedCandidate;
        private set
        {
            if (SetProperty(ref _selectedCandidate, value))
            {
                RaisePropertyChanged(nameof(CandidateSummary));
                RaiseActions();
            }
        }
    }

    public IReadOnlyList<ProviderCommitCandidateRecord> CommitCandidates
    {
        get => _commitCandidates;
        private set
        {
            if (SetProperty(ref _commitCandidates, value))
            {
                RaiseActions();
            }
        }
    }

    public ProviderCommitCandidateRecord? SelectedCommitCandidate
    {
        get => _selectedCommitCandidate;
        private set
        {
            if (SetProperty(ref _selectedCommitCandidate, value))
            {
                RaisePropertyChanged(nameof(CommitCandidateSummary));
                RaiseActions();
            }
        }
    }

    public IReadOnlyList<ProviderPublicationCandidateRecord> PublicationCandidates
    {
        get => _publicationCandidates;
        private set
        {
            if (SetProperty(ref _publicationCandidates, value))
            {
                RaiseActions();
            }
        }
    }

    public ProviderPublicationCandidateRecord? SelectedPublicationCandidate
    {
        get => _selectedPublicationCandidate;
        private set
        {
            if (SetProperty(ref _selectedPublicationCandidate, value))
            {
                RaisePropertyChanged(nameof(PublicationCandidateSummary));
                RaiseActions();
            }
        }
    }

    public string ReviewSummary => Review is null
        ? "尚无可审阅 Return。"
        : $"{Review.ReviewStatus} · Return {Review.ReturnId ?? "—"} · "
          + $"文件 {Review.ChangedFileCount}/5 · payload {Review.PayloadBytes}/262144 bytes";

    public string CandidateSummary => SelectedCandidate is null
        ? "尚无落地候选。"
        : $"{SelectedCandidate.Status} · 文件 {SelectedCandidate.ChangedFileCount} · "
          + $"validation {SelectedCandidate.ValidationChecks.Count} 项 · "
          + "adoption_ready 仅代表本地可确定性重放，不是 merge-ready。";

    public string CommitCandidateSummary => SelectedCommitCandidate is null
        ? "尚无本地提交候选；只有 adoption_ready 才能准备新的人工审批。"
        : $"{SelectedCommitCandidate.Status} · commit {SelectedCommitCandidate.CommitSha ?? "—"} · "
          + $"tree {SelectedCommitCandidate.TreeSha ?? "—"} · {SelectedCommitCandidate.LocalRef} · "
          + "commit_ready != pushed != PR-ready != merge-ready。";

    public string PublicationCandidateSummary => SelectedPublicationCandidate is null
        ? "尚无远端发布候选；只有 commit_ready 才能准备一次新的 Push + Draft PR 审批。"
        : $"{SelectedPublicationCandidate.Status} · {SelectedPublicationCandidate.RepositorySlug} · "
          + $"base {SelectedPublicationCandidate.BaseRef}@{SelectedPublicationCandidate.BaseCommit[..12]} · "
          + $"head {SelectedPublicationCandidate.CommitSha[..12]} · "
          + $"PR {(SelectedPublicationCandidate.PrNumber?.ToString() ?? "—")} · "
          + "pr_ready != CI-green != merge-ready。";

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

    public bool CanAccept => !IsBusy && _gateway is not null && Review?.ReviewStatus == "reviewable";
    public bool CanReject => !IsBusy && _gateway is not null && Review?.ReviewStatus == "reviewable";
    public bool CanPrepareCommit =>
        !IsBusy
        && _gateway is not null
        && SelectedCandidate?.Status == "adoption_ready"
        && !CommitCandidates.Any(item => item.AdoptionCandidateId == SelectedCandidate.CandidateId);
    public bool CanPreparePublication =>
        !IsBusy
        && _gateway is not null
        && SelectedCommitCandidate?.Status == "commit_ready"
        && !PublicationCandidates.Any(
            item => item.CommitCandidateId == SelectedCommitCandidate.CommitCandidateId);

    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand AcceptCommand { get; }
    public AsyncRelayCommand RejectCommand { get; }
    public AsyncRelayCommand RefreshCandidateCommand { get; }
    public AsyncRelayCommand PrepareCommitCommand { get; }
    public AsyncRelayCommand RefreshCommitCommand { get; }
    public AsyncRelayCommand PreparePublicationCommand { get; }
    public AsyncRelayCommand RefreshPublicationCommand { get; }

    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        IsBusy = true;
        StatusMessage = "正在读取 Review、Adoption、Commit 与 Publication 安全事实……";
        try
        {
            var selectedId = SelectedSession?.SessionId;
            var sessions = await _gateway.GetSessionsAsync(cancellationToken).ConfigureAwait(true);
            ReviewableSessions = sessions
                .Where(item => item.Status == "ready_for_review")
                .OrderByDescending(item => item.UpdatedAt)
                .Take(100)
                .ToArray();
            SelectedSession = ReviewableSessions.FirstOrDefault(item => item.SessionId == selectedId)
                ?? (ReviewableSessions.Count > 0 ? ReviewableSessions[0] : null);
            if (SelectedSession is null)
            {
                Review = null;
                Candidates = [];
                SelectedCandidate = null;
                CommitCandidates = [];
                SelectedCommitCandidate = null;
                PublicationCandidates = [];
                SelectedPublicationCandidate = null;
                StatusMessage = "当前没有 ready_for_review Session。";
                return;
            }
            Review = await _gateway.GetReviewAsync(
                SelectedSession.SessionId,
                cancellationToken).ConfigureAwait(true);
            await RefreshCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshCommitCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = Review.ReviewStatus == "legacy_no_artifact"
                ? "该 Session 来自旧格式，只能查看历史，不能接受落地、创建提交或准备远端发布。"
                : "Review 已重新验签；Commit 与 Publication 都需要各自独立的 Approval Center 明确批准。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("刷新失败；已有安全投影已保留。", exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task AcceptAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway ?? throw new InvalidOperationException("Smoke 模式不能接受 Review。");
        var session = SelectedSession ?? throw new InvalidOperationException("请先选择 ready_for_review Session。");
        if (!CanAccept)
        {
            throw new InvalidOperationException("当前 Return 不可接受。");
        }
        IsBusy = true;
        try
        {
            Review = await gateway.AcceptAsync(
                session.SessionId,
                $"windows-review-accept-{session.SessionId}-{Guid.NewGuid():N}",
                cancellationToken).ConfigureAwait(true);
            await RefreshCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshCommitCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "Return 已接受；先形成 adoption_ready，再通过独立审批逐步进入 Commit 与 Publication。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task RejectAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway ?? throw new InvalidOperationException("Smoke 模式不能拒绝 Review。");
        var session = SelectedSession ?? throw new InvalidOperationException("请先选择 ready_for_review Session。");
        if (!CanReject)
        {
            throw new InvalidOperationException("当前 Return 不可拒绝。");
        }
        IsBusy = true;
        try
        {
            Review = await gateway.RejectAsync(
                session.SessionId,
                $"windows-review-reject-{session.SessionId}-{Guid.NewGuid():N}",
                cancellationToken).ConfigureAwait(true);
            Candidates = [];
            SelectedCandidate = null;
            CommitCandidates = [];
            SelectedCommitCandidate = null;
            PublicationCandidates = [];
            SelectedPublicationCandidate = null;
            StatusMessage = "Return 已拒绝；决策不可反转，未创建后续候选。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task RefreshCandidateAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        IsBusy = true;
        try
        {
            await RefreshCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshCommitCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "候选状态已刷新；所有 readiness 状态都有明确边界。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("候选刷新失败；已有安全投影已保留。", exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task PrepareCommitAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway ?? throw new InvalidOperationException("Smoke 模式不能准备本地提交。");
        var candidate = SelectedCandidate ?? throw new InvalidOperationException("请先选择 Adoption Candidate。");
        if (!CanPrepareCommit)
        {
            throw new InvalidOperationException("只有 adoption_ready 且尚无 Commit Candidate 时才能准备本地提交。");
        }
        IsBusy = true;
        try
        {
            SelectedCommitCandidate = await gateway.PrepareCommitAsync(
                candidate.CandidateId,
                $"windows-commit-prepare-{candidate.CandidateId}",
                cancellationToken).ConfigureAwait(true);
            await RefreshCommitCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "Commit Candidate 已准备；审批中心批准后只创建本地 Git object/ref。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task RefreshCommitAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        IsBusy = true;
        try
        {
            await RefreshCommitCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "Commit Candidate 已刷新；只有 commit_ready 才能准备 Publication 审批。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("Commit Candidate 刷新失败；已有安全投影已保留。", exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task PreparePublicationAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway ?? throw new InvalidOperationException("Smoke 模式不能准备远端发布。");
        var commit = SelectedCommitCandidate ?? throw new InvalidOperationException("请先选择 Commit Candidate。");
        if (!CanPreparePublication)
        {
            throw new InvalidOperationException("只有 commit_ready 且尚无 Publication Candidate 时才能准备发布审批。");
        }
        IsBusy = true;
        try
        {
            SelectedPublicationCandidate = await gateway.PreparePublicationAsync(
                commit.CommitCandidateId,
                $"windows-publication-prepare-{commit.CommitCandidateId}",
                cancellationToken).ConfigureAwait(true);
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "Publication Candidate 已准备；只有审批中心批准 exact repo/base/commit/ref 后才允许 Push + Draft PR。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task RefreshPublicationAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        IsBusy = true;
        try
        {
            await RefreshPublicationCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = "Publication Candidate 已刷新；pr_ready != CI-green != merge-ready。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("Publication Candidate 刷新失败；已有安全投影已保留。", exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCandidatesCoreAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway!;
        var selectedId = Review?.CandidateId ?? SelectedCandidate?.CandidateId;
        Candidates = (await gateway.GetCandidatesAsync(cancellationToken).ConfigureAwait(true))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        SelectedCandidate = Candidates.FirstOrDefault(item => item.CandidateId == selectedId)
            ?? (Candidates.Count > 0 ? Candidates[0] : null);
    }

    private async Task RefreshCommitCandidatesCoreAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway!;
        var selectedId = SelectedCommitCandidate?.CommitCandidateId;
        CommitCandidates = (await gateway.GetCommitCandidatesAsync(cancellationToken).ConfigureAwait(true))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        SelectedCommitCandidate = CommitCandidates.FirstOrDefault(item => item.CommitCandidateId == selectedId)
            ?? CommitCandidates.FirstOrDefault(
                item => item.AdoptionCandidateId == SelectedCandidate?.CandidateId)
            ?? (CommitCandidates.Count > 0 ? CommitCandidates[0] : null);
    }

    private async Task RefreshPublicationCandidatesCoreAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway!;
        var selectedId = SelectedPublicationCandidate?.PublicationCandidateId;
        PublicationCandidates = (await gateway.GetPublicationCandidatesAsync(cancellationToken).ConfigureAwait(true))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        SelectedPublicationCandidate = PublicationCandidates.FirstOrDefault(
                item => item.PublicationCandidateId == selectedId)
            ?? PublicationCandidates.FirstOrDefault(
                item => item.CommitCandidateId == SelectedCommitCandidate?.CommitCandidateId)
            ?? (PublicationCandidates.Count > 0 ? PublicationCandidates[0] : null);
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanAccept));
        RaisePropertyChanged(nameof(CanReject));
        RaisePropertyChanged(nameof(CanPrepareCommit));
        RaisePropertyChanged(nameof(CanPreparePublication));
        RefreshCommand.NotifyCanExecuteChanged();
        AcceptCommand.NotifyCanExecuteChanged();
        RejectCommand.NotifyCanExecuteChanged();
        RefreshCandidateCommand.NotifyCanExecuteChanged();
        PrepareCommitCommand.NotifyCanExecuteChanged();
        RefreshCommitCommand.NotifyCanExecuteChanged();
        PreparePublicationCommand.NotifyCanExecuteChanged();
        RefreshPublicationCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception) =>
        StatusMessage = FormatError("Review/Commit/Publication 操作失败；已有安全投影已保留。", exception);

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

    private static ProviderSessionRecord SmokeSession() => new(
        "22222222-2222-2222-2222-222222222222",
        "handoff-review-smoke",
        "codex",
        "ready_for_review",
        new string('a', 64),
        new string('b', 64),
        ProviderBudgetRecord.Fixed,
        2,
        20,
        1,
        "return-review-smoke",
        null,
        ProviderUsageUnknown: true,
        DateTimeOffset.UtcNow.AddMinutes(-2),
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow,
        "Smoke Review Session");

    private static ProviderReviewRecord SmokeReview(string sessionId) => new(
        sessionId,
        "return-review-smoke",
        "reviewable",
        new string('c', 64),
        new string('d', 64),
        1,
        16,
        [new ProviderReviewFileRecord("add", "docs/review.txt", 16, null, new string('e', 64))],
        "--- a/docs/review.txt\n+++ b/docs/review.txt\n+reviewed change\n",
        null,
        "33333333-3333-3333-3333-333333333333");

    private static ProviderAdoptionCandidateRecord SmokeCandidate(string sessionId) => new(
        "33333333-3333-3333-3333-333333333333",
        sessionId,
        "return-review-smoke",
        "adoption_ready",
        new string('f', 40),
        new string('c', 64),
        1,
        ["change_set_replayed", "git_diff_check"],
        null,
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow,
        DateTimeOffset.UtcNow);

    private static ProviderCommitCandidateRecord SmokeCommitCandidate(
        string sessionId,
        string adoptionCandidateId) => new(
        "44444444-4444-4444-4444-444444444444",
        adoptionCandidateId,
        sessionId,
        "return-review-smoke",
        "commit_ready",
        new string('f', 40),
        new string('c', 64),
        "55555555-5555-5555-5555-555555555555",
        "PicotooPet adoption candidate 44444444-4444-4444-4444-444444444444",
        new string('a', 64),
        new string('b', 40),
        new string('d', 40),
        "refs/picotoopet/commit-candidates/44444444-4444-4444-4444-444444444444",
        ["tree_diff_exact", "commit_parent_exact", "local_ref_cas"],
        null,
        DateTimeOffset.UtcNow,
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow,
        DateTimeOffset.UtcNow);

    private static ProviderPublicationCandidateRecord SmokePublicationCandidate(
        string sessionId,
        string commitCandidateId) => new(
        "66666666-6666-6666-6666-666666666666",
        commitCandidateId,
        sessionId,
        "77777777-7777-7777-7777-777777777777",
        "waiting_approval",
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "jerryjwres-hue/picotoopet-v2.0",
        "feature/verified-baseline",
        new string('f', 40),
        new string('d', 40),
        new string('c', 64),
        "refs/heads/picotoopet/commit-candidates/66666666-6666-6666-6666-666666666666",
        "picotoopet/commit-candidates/66666666-6666-6666-6666-666666666666",
        "88888888-8888-8888-8888-888888888888",
        new string('a', 64),
        new string('b', 64),
        null,
        null,
        null,
        [],
        null,
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow,
        null);
}