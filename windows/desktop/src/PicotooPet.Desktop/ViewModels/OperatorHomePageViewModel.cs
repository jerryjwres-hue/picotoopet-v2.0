using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式首页：目标中心提交高层意图；任务、状态和交接事实继续来自 Mac Core。</summary>
public sealed class OperatorHomePageViewModel : PageViewModel
{
    private static readonly IReadOnlyList<GoalDepthOption> DepthOptions =
    [
        new("快速", "quick", "较少检索，适合先判断方向"),
        new("标准", "standard", "平衡覆盖度与处理时间"),
        new("深入", "deep", "更多只读研究与证据筛选"),
    ];

    private readonly ControlCenterSession? _session;
    private OperatorProjection _projection;
    private AssistantPetIndicator _coreIndicator;
    private AssistantPetIndicator _workerIndicator;
    private AssistantPetIndicator _windowsIndicator;
    private double? _cpuPercent;
    private double? _memoryPercent;
    private double? _diskPercent;
    private IReadOnlyList<GoalTemplateRecord> _goalTemplates = Array.Empty<GoalTemplateRecord>();
    private GoalDepthOption _selectedGoalDepth = DepthOptions[1];
    private string _goalObjective = string.Empty;
    private string? _selectedGoalType;
    private HumanGoalRecord? _currentGoal;
    private GoalHandoffMetadataRecord? _currentHandoff;
    private bool _isGoalBusy;
    private string _goalError = string.Empty;

    public OperatorHomePageViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
        : base("首页")
    {
        _session    = session ?? throw new ArgumentNullException(nameof(session));
        _projection = OperatorProjection.FromSnapshot(snapshot);
        ApplyHealthIndicators(snapshot);
    }

    private OperatorHomePageViewModel(ControlCenterSessionSnapshot snapshot)
        : base("首页")
    {
        _projection = OperatorProjection.FromSnapshot(snapshot);
        ApplyHealthIndicators(snapshot);
    }

    public OperatorProjection Projection
    {
        get => _projection;
        private set
        {
            if (SetProperty(ref _projection, value))
            {
                RaiseProjectionProperties();
            }
        }
    }

    public IReadOnlyList<OperatorTaskCard> PendingReview => Projection.PendingReview.Take(4).ToArray();
    public IReadOnlyList<OperatorTaskCard> InProgress => Projection.InProgress.Take(4).ToArray();
    public IReadOnlyList<OperatorTaskCard> Completed => Projection.Completed.Take(4).ToArray();

    /// <summary>最近任务只合并现有事实桶，不新增任务副本或第二套状态。</summary>
    public IReadOnlyList<OperatorTaskCard> RecentTasks =>
        Projection.PendingReview
            .Concat(Projection.InProgress)
            .Concat(Projection.Completed)
            .OrderByDescending(item => item.UpdatedAt)
            .ThenBy(item => item.TaskId, StringComparer.Ordinal)
            .Take(6)
            .ToArray();

    public int PendingReviewCount => Projection.PendingReview.Count;
    public int InProgressCount => Projection.InProgress.Count;
    public int CompletedCount => Projection.Completed.Count;
    public string CoreStatus => Projection.CoreStatus;
    public string WorkerStatus => Projection.WorkerStatus;
    public string WindowsStatus => Projection.WindowsStatus;
    public string SystemSummary => Projection.SystemSummary;
    public AssistantPetIndicator CoreIndicator => _coreIndicator;
    public AssistantPetIndicator WorkerIndicator => _workerIndicator;
    public AssistantPetIndicator WindowsIndicator => _windowsIndicator;
    public AssistantPetIndicator SystemIndicator =>
        _coreIndicator == AssistantPetIndicator.Orange || _workerIndicator == AssistantPetIndicator.Orange
            ? AssistantPetIndicator.Orange
            : _coreIndicator == AssistantPetIndicator.Gray || _workerIndicator == AssistantPetIndicator.Gray
                ? AssistantPetIndicator.Gray
                : AssistantPetIndicator.Green;

    /// <summary>资源条使用 0 作为不可用时的安全绘制值；可见文本仍明确显示破折号。</summary>
    public double CpuPercent => _cpuPercent ?? 0d;
    public double MemoryPercent => _memoryPercent ?? 0d;
    public double DiskPercent => _diskPercent ?? 0d;
    public string CpuText => FormatMetric(_cpuPercent);
    public string MemoryText => FormatMetric(_memoryPercent);
    public string DiskText => FormatMetric(_diskPercent);

    /// <summary>模板由 Mac Core 返回；Windows 只缓存当前展示副本。</summary>
    public IReadOnlyList<GoalTemplateRecord> GoalTemplates
    {
        get => _goalTemplates;
        private set => SetProperty(ref _goalTemplates, value);
    }

    public IReadOnlyList<GoalDepthOption> GoalDepthOptions => DepthOptions;

    public GoalDepthOption SelectedGoalDepth
    {
        get => _selectedGoalDepth;
        set
        {
            if (SetProperty(ref _selectedGoalDepth, value))
            {
                RaisePropertyChanged(nameof(CanCreateGoal));
            }
        }
    }

    public string GoalObjective
    {
        get => _goalObjective;
        set
        {
            if (SetProperty(ref _goalObjective, value ?? string.Empty))
            {
                RaisePropertyChanged(nameof(CanCreateGoal));
            }
        }
    }

    public string? SelectedGoalType
    {
        get => _selectedGoalType;
        private set
        {
            if (SetProperty(ref _selectedGoalType, value))
            {
                RaisePropertyChanged(nameof(CanCreateGoal));
                RaisePropertyChanged(nameof(SelectedGoalTemplateTitle));
            }
        }
    }

    public string SelectedGoalTemplateTitle =>
        GoalTemplates.FirstOrDefault(item => string.Equals(item.GoalType, SelectedGoalType, StringComparison.Ordinal))?.Title
        ?? "选择目标类型";

    public HumanGoalRecord? CurrentGoal
    {
        get => _currentGoal;
        private set
        {
            if (SetProperty(ref _currentGoal, value))
            {
                RaiseGoalStatusProperties();
            }
        }
    }

    public GoalHandoffMetadataRecord? CurrentHandoff
    {
        get => _currentHandoff;
        private set
        {
            if (SetProperty(ref _currentHandoff, value))
            {
                RaisePropertyChanged(nameof(HandoffReady));
                RaisePropertyChanged(nameof(HandoffSummary));
            }
        }
    }

    public bool IsGoalBusy
    {
        get => _isGoalBusy;
        private set
        {
            if (SetProperty(ref _isGoalBusy, value))
            {
                RaisePropertyChanged(nameof(CanCreateGoal));
                RaisePropertyChanged(nameof(GoalStatusText));
            }
        }
    }

    public string GoalError
    {
        get => _goalError;
        private set
        {
            if (SetProperty(ref _goalError, value))
            {
                RaisePropertyChanged(nameof(HasGoalError));
                RaisePropertyChanged(nameof(GoalStatusDetail));
            }
        }
    }

    public bool HasGoalError => !string.IsNullOrWhiteSpace(GoalError);

    public bool CanCreateGoal =>
        _session is not null
        && !IsGoalBusy
        && !string.IsNullOrWhiteSpace(SelectedGoalType)
        && !string.IsNullOrWhiteSpace(GoalObjective)
        && GoalObjective.Trim().Length is >= 4 and <= 2000;

    public bool HandoffReady => CurrentHandoff?.HandoffReady == true;

    public string HandoffSummary => HandoffReady
        ? $"交接包已就绪 · {CurrentHandoff!.PackageName} · Prompt {CurrentHandoff.PromptVersion}"
        : "视频目标完成后，Mac 会在这里提供可下载交接包和固定 GPT 提示词。";

    public string GoalStatusText
    {
        get
        {
            if (IsGoalBusy)
            {
                return "正在提交目标…";
            }
            if (CurrentGoal is null)
            {
                return _session is null ? "未连接目标服务" : "等待你的目标";
            }
            return CurrentGoal.Status switch
            {
                "Ready" => "等待执行",
                "Running" => "正在自动执行",
                "Deferred" => "等待能力恢复",
                "Completed" => "已完成",
                "Failed" => "执行失败",
                "Cancelled" => "已取消",
                _ => CurrentGoal.Status,
            };
        }
    }

    public string GoalStatusDetail
    {
        get
        {
            if (HasGoalError)
            {
                return GoalError;
            }
            if (CurrentGoal is null)
            {
                return _session is null
                    ? "Smoke/离线状态不会伪造运行中的目标。"
                    : "选择一个建议目标或输入你的目标，Mac 会自动规划只读研究、分析与交接。";
            }
            return CurrentGoal.Status switch
            {
                "Ready" => "目标已记录；当前所需能力尚未创建可执行任务时会继续等待。",
                "Running" => "Mac Core 正在按固定 Workflow 推进；Windows 只显示服务端事实。",
                "Deferred" => "所需本地模型或研究能力暂不可用；恢复后会继续推进。",
                "Completed" when HandoffReady => "分析与 Web GPT 交接包均已通过 Core 完整性检查。",
                "Completed" => "目标已完成；如果该目标需要视频交接包，正在检查其可用性。",
                "Failed" => "Mac Core 已将该目标标记失败；任务历史中保留可追溯事实。",
                "Cancelled" => "该目标已取消，不会继续创建新的执行任务。",
                _ => "状态来自 Mac Core。",
            };
        }
    }

    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        Projection = OperatorProjection.FromSnapshot(snapshot);
        ApplyHealthIndicators(snapshot);
    }

    /// <summary>接收独立本地只读采样；不会修改 Session、Worker 或任务快照。</summary>
    public void UpdateResourceSnapshot(WindowsResourceSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        _cpuPercent    = WindowsResourceSnapshot.Normalize(snapshot.CpuPercent);
        _memoryPercent = WindowsResourceSnapshot.Normalize(snapshot.MemoryPercent);
        _diskPercent   = WindowsResourceSnapshot.Normalize(snapshot.DiskPercent);

        RaisePropertyChanged(nameof(CpuPercent));
        RaisePropertyChanged(nameof(MemoryPercent));
        RaisePropertyChanged(nameof(DiskPercent));
        RaisePropertyChanged(nameof(CpuText));
        RaisePropertyChanged(nameof(MemoryText));
        RaisePropertyChanged(nameof(DiskText));
    }

    /// <summary>从 Core 刷新模板与最近目标；不根据 Windows 本地状态推断完成度。</summary>
    public async Task RefreshGoalsAsync(CancellationToken cancellationToken = default)
    {
        if (_session is null || IsGoalBusy)
        {
            return;
        }

        try
        {
            var templatesTask = _session.GetGoalTemplatesAsync(cancellationToken);
            var goalsTask = _session.GetGoalsAsync(cancellationToken);
            await Task.WhenAll(templatesTask, goalsTask).ConfigureAwait(false);

            var templates = await templatesTask.ConfigureAwait(false);
            var goals = await goalsTask.ConfigureAwait(false);
            GoalTemplates = templates;
            if (SelectedGoalType is null || !templates.Any(item => item.GoalType == SelectedGoalType))
            {
                SelectedGoalType = templates.FirstOrDefault()?.GoalType;
            }
            RaisePropertyChanged(nameof(SelectedGoalTemplateTitle));

            CurrentGoal = goals
                .Where(item => string.Equals(item.Origin, "human", StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(item => item.UpdatedAt)
                .ThenByDescending(item => item.CreatedAt)
                .FirstOrDefault();
            GoalError = string.Empty;
            await RefreshCurrentHandoffAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            GoalError = ToSafeGoalError(exception);
        }
    }

    /// <summary>选择 Core 提供的模板；示例只在输入为空时填入，用户仍可自由修改目标。</summary>
    public void SelectGoalTemplate(GoalTemplateRecord template)
    {
        ArgumentNullException.ThrowIfNull(template);
        if (!GoalTemplates.Any(item => string.Equals(item.GoalType, template.GoalType, StringComparison.Ordinal)))
        {
            return;
        }

        SelectedGoalType = template.GoalType;
        if (string.IsNullOrWhiteSpace(GoalObjective))
        {
            GoalObjective = template.Example;
        }
    }

    /// <summary>创建一个高层 Goal；Windows 不传 task type、priority、model、prompt 或 workflow。</summary>
    public async Task CreateGoalAsync(CancellationToken cancellationToken = default)
    {
        if (_session is null || !CanCreateGoal || SelectedGoalType is null)
        {
            return;
        }

        IsGoalBusy = true;
        GoalError = string.Empty;
        CurrentHandoff = null;
        try
        {
            var request = new HumanGoalCreateRequest(
                SelectedGoalType,
                GoalObjective.Trim(),
                SelectedGoalDepth.Value);
            CurrentGoal = await _session.CreateGoalAsync(
                request,
                $"windows-goal-{Guid.NewGuid():N}",
                cancellationToken).ConfigureAwait(false);
            await RefreshCurrentHandoffAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            GoalError = ToSafeGoalError(exception);
        }
        finally
        {
            IsGoalBusy = false;
            RaiseGoalStatusProperties();
        }
    }

    public async Task<string> GetCurrentHandoffPromptAsync(CancellationToken cancellationToken = default)
    {
        if (_session is null || CurrentGoal is null || !HandoffReady)
        {
            throw new InvalidOperationException("当前目标还没有可用的 Web GPT 交接提示词。");
        }
        return await _session.GetGoalHandoffPromptAsync(CurrentGoal.GoalId, cancellationToken)
            .ConfigureAwait(false);
    }

    public async Task<byte[]> DownloadCurrentHandoffAsync(CancellationToken cancellationToken = default)
    {
        if (_session is null || CurrentGoal is null || !HandoffReady)
        {
            throw new InvalidOperationException("当前目标还没有可下载的 Web GPT 交接包。");
        }
        return await _session.DownloadGoalHandoffAsync(CurrentGoal.GoalId, cancellationToken)
            .ConfigureAwait(false);
    }

    public NewTaskWizardViewModel CreateNewTaskWizard() =>
        _session is null
            ? NewTaskWizardViewModel.CreateForSmokeTest()
            : new NewTaskWizardViewModel(_session, _session.Snapshot);

    public static OperatorHomePageViewModel CreateForSmokeTest(
        ControlCenterSessionSnapshot snapshot) => new(snapshot);

    private async Task RefreshCurrentHandoffAsync(CancellationToken cancellationToken)
    {
        CurrentHandoff = null;
        if (_session is null
            || CurrentGoal is null
            || !string.Equals(CurrentGoal.Status, "Completed", StringComparison.Ordinal)
            || CurrentGoal.IntentType is not ("video.creative" or "product.research_to_video"))
        {
            return;
        }

        try
        {
            CurrentHandoff = await _session.GetGoalHandoffAsync(CurrentGoal.GoalId, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (ApiException exception) when (exception.StatusCode is 404 or 409)
        {
            // 完成事实与交接包可用性分开判断；尚未存在时保持不可用，不伪造 ready。
            CurrentHandoff = null;
        }
    }

    private void ApplyHealthIndicators(ControlCenterSessionSnapshot snapshot)
    {
        var connectionState = snapshot.State.Connection.State;
        _coreIndicator = connectionState switch
        {
            ConnectionState.Online => AssistantPetIndicator.Green,
            ConnectionState.Offline => AssistantPetIndicator.Gray,
            ConnectionState.AuthenticationFailed or ConnectionState.Faulted => AssistantPetIndicator.Orange,
            _ => AssistantPetIndicator.Orange,
        };

        var worker = snapshot.State.Worker;
        _workerIndicator = connectionState == ConnectionState.Offline
            ? AssistantPetIndicator.Gray
            : worker.Available
                ? string.Equals(worker.Reason, "degraded", StringComparison.OrdinalIgnoreCase)
                    ? AssistantPetIndicator.Orange
                    : AssistantPetIndicator.Green
                : string.Equals(worker.Reason, "degraded", StringComparison.OrdinalIgnoreCase)
                    ? AssistantPetIndicator.Orange
                    : AssistantPetIndicator.Gray;

        // Windows UI 本身正在运行才会生成该 ViewModel，因此本地壳状态为绿色事实。
        _windowsIndicator = AssistantPetIndicator.Green;

        RaisePropertyChanged(nameof(CoreIndicator));
        RaisePropertyChanged(nameof(WorkerIndicator));
        RaisePropertyChanged(nameof(WindowsIndicator));
        RaisePropertyChanged(nameof(SystemIndicator));
    }

    private static string FormatMetric(double? value) =>
        value is null
            ? "—"
            : $"{Math.Round(value.Value):0}%";

    private static string ToSafeGoalError(Exception exception) => exception switch
    {
        ApiException api when api.StatusCode is 401 or 403 => "目标中心认证失败，请重新连接 Mac Core。",
        ApiException api when api.StatusCode == 422 => "目标内容或目标类型不符合当前 Core 合同，请检查后重试。",
        ApiException api when api.Retryable => "目标中心暂时不可用，请稍后重试。",
        InvalidOperationException invalid => invalid.Message,
        _ => "目标中心暂时无法完成这次操作；现有任务和目标事实没有被修改。",
    };

    private void RaiseGoalStatusProperties()
    {
        RaisePropertyChanged(nameof(GoalStatusText));
        RaisePropertyChanged(nameof(GoalStatusDetail));
        RaisePropertyChanged(nameof(HandoffReady));
        RaisePropertyChanged(nameof(HandoffSummary));
        RaisePropertyChanged(nameof(CanCreateGoal));
    }

    private void RaiseProjectionProperties()
    {
        RaisePropertyChanged(nameof(PendingReview));
        RaisePropertyChanged(nameof(InProgress));
        RaisePropertyChanged(nameof(Completed));
        RaisePropertyChanged(nameof(RecentTasks));
        RaisePropertyChanged(nameof(PendingReviewCount));
        RaisePropertyChanged(nameof(InProgressCount));
        RaisePropertyChanged(nameof(CompletedCount));
        RaisePropertyChanged(nameof(CoreStatus));
        RaisePropertyChanged(nameof(WorkerStatus));
        RaisePropertyChanged(nameof(WindowsStatus));
        RaisePropertyChanged(nameof(SystemSummary));
    }
}

/// <summary>固定研究深度展示项；值与 Mac Core 的 quick/standard/deep 合同一一对应。</summary>
public sealed record GoalDepthOption(string Title, string Value, string Description)
{
    public override string ToString() => Title;
}
