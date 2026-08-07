using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 10D-B 只读 Review、固定接受/拒绝与 Adoption Candidate 状态。</summary>
public sealed class ProviderReviewViewModel : ObservableObject
{
    private readonly IProviderReviewGateway? _gateway;
    private IReadOnlyList<ProviderSessionRecord> _reviewableSessions = [];
    private ProviderSessionRecord? _selectedSession;
    private ProviderReviewRecord? _review;
    private IReadOnlyList<ProviderAdoptionCandidateRecord> _candidates = [];
    private ProviderAdoptionCandidateRecord? _selectedCandidate;
    private string _statusMessage = "Review 只读；接受后只形成本地 adoption_ready 候选，不会自动提交或发布。";
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

        if (initializeSmoke)
        {
            var session = SmokeSession();
            ReviewableSessions = [session];
            SelectedSession = session;
            Review = SmokeReview(session.SessionId);
            Candidates = [SmokeCandidate(session.SessionId)];
            SelectedCandidate = Candidates[0];
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

    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand AcceptCommand { get; }
    public AsyncRelayCommand RejectCommand { get; }
    public AsyncRelayCommand RefreshCandidateCommand { get; }

    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }
        IsBusy = true;
        StatusMessage = "正在读取 ready_for_review Session 与不可变 Review Artifact……";
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
                ?? ReviewableSessions.FirstOrDefault();
            if (SelectedSession is null)
            {
                Review = null;
                Candidates = [];
                SelectedCandidate = null;
                StatusMessage = "当前没有 ready_for_review Session。";
                return;
            }
            Review = await _gateway.GetReviewAsync(
                SelectedSession.SessionId,
                cancellationToken).ConfigureAwait(true);
            await RefreshCandidatesCoreAsync(cancellationToken).ConfigureAwait(true);
            StatusMessage = Review.ReviewStatus == "legacy_no_artifact"
                ? "该 Session 来自 2.3.13.2 旧格式，只能查看历史，不能接受落地。"
                : "Review 已重新验签；diff 只读，接受/拒绝不可反转。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError("刷新失败；已有 Review 安全投影已保留。", exception);
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
            StatusMessage = "Return 已接受；Mac Worker 只会在新隔离 worktree 中重放，不会 commit/push/PR/merge。";
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
            StatusMessage = "Return 已拒绝；决策不可反转，未创建落地候选。";
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
            StatusMessage = "Adoption Candidate 状态已刷新；adoption_ready 不等于 merge-ready。";
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

    private async Task RefreshCandidatesCoreAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway!;
        var selectedId = Review?.CandidateId ?? SelectedCandidate?.CandidateId;
        Candidates = (await gateway.GetCandidatesAsync(cancellationToken).ConfigureAwait(true))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        SelectedCandidate = Candidates.FirstOrDefault(item => item.CandidateId == selectedId)
            ?? Candidates.FirstOrDefault();
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanAccept));
        RaisePropertyChanged(nameof(CanReject));
        RefreshCommand.NotifyCanExecuteChanged();
        AcceptCommand.NotifyCanExecuteChanged();
        RejectCommand.NotifyCanExecuteChanged();
        RefreshCandidateCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception) =>
        StatusMessage = FormatError("Review 操作失败；已有安全投影已保留。", exception);

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
        "queued",
        new string('f', 40),
        new string('c', 64),
        1,
        [],
        null,
        DateTimeOffset.UtcNow.AddMinutes(-1),
        DateTimeOffset.UtcNow,
        null);
}
