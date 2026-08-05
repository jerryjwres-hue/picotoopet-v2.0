using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>结果中心支持的互斥只读筛选。</summary>
public enum ResultsFilter
{
    All,
    Diagnostic,
    Archived,
}

/// <summary>供 WPF ComboBox 显示的结果筛选项。</summary>
public sealed record ResultsFilterOption(
    ResultsFilter Value,
    string Label);

/// <summary>单个可见结果的安全元数据；不包含对象路径、正文或任意 manifest。</summary>
public sealed class ResultRowViewModel
{
    private const string DiagnosticTaskType = "system.diagnostic_snapshot";

    private ResultRowViewModel(TaskRecord task)
    {
        TaskId = task.TaskId;
        ResultId = task.ResultId
            ?? throw new ArgumentException("结果行必须包含 result_id。", nameof(task));
        TaskType = task.TaskType;
        Status = task.Status;
        UpdatedAt = task.UpdatedAt;
        DisplayType = task.TaskType == DiagnosticTaskType
            ? "系统诊断快照"
            : task.TaskType;
        DisplayStatus = task.Status switch
        {
            "Completed" => "已完成",
            "Archived"  => "已归档",
            _           => task.Status,
        };
        CanPreview = task.TaskType == DiagnosticTaskType
            && task.Status is "Completed" or "Archived";
        PreviewUnavailableReason = CanPreview
            ? "通过固定诊断合同加载安全预览。"
            : "当前结果类型尚不支持安全预览；不会回退到任意内容浏览。";
    }

    public string TaskId { get; }

    public string ResultId { get; }

    public string TaskType { get; }

    public string Status { get; }

    public string DisplayType { get; }

    public string DisplayStatus { get; }

    public DateTimeOffset UpdatedAt { get; }

    public bool CanPreview { get; }

    public string PreviewUnavailableReason { get; }

    /// <summary>从已具备结果 ID 的终态任务创建结果行。</summary>
    public static ResultRowViewModel FromRecord(TaskRecord task)
    {
        ArgumentNullException.ThrowIfNull(task);
        return new ResultRowViewModel(task);
    }
}

/// <summary>展示真实结果列表并只允许固定合同的安全预览。</summary>
public sealed class ResultsPageViewModel : PageViewModel
{
    private static readonly IReadOnlyList<ResultsFilterOption> DefaultFilters =
        new ResultsFilterOption[]
        {
            new(ResultsFilter.All, "全部结果"),
            new(ResultsFilter.Diagnostic, "系统诊断"),
            new(ResultsFilter.Archived, "已归档"),
        };

    private readonly ControlCenterSession? _session;
    private readonly IReadOnlyList<ResultsFilterOption> _filterOptions = DefaultFilters;
    private IReadOnlyList<ResultRowViewModel> _allResults = Array.Empty<ResultRowViewModel>();
    private IReadOnlyList<ResultRowViewModel> _visibleResults = Array.Empty<ResultRowViewModel>();
    private ResultsFilter _selectedFilter;
    private ResultRowViewModel? _selectedResult;
    private DiagnosticResultViewModel? _diagnosticPreview;
    private bool _isPreviewVisible;
    private bool _isBusy;
    private string _statusMessage = "结果列表来自 Mac Core 已完成任务快照。";

    /// <summary>创建绑定真实 Session 的结果中心。</summary>
    public ResultsPageViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
        : base("结果")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        ArgumentNullException.ThrowIfNull(snapshot);
        ApplyTasks(snapshot.State.Tasks.Tasks);
    }

    private ResultsPageViewModel(IReadOnlyList<TaskRecord> tasks)
        : base("结果")
    {
        ApplyTasks(tasks);
    }

    public IReadOnlyList<ResultsFilterOption> FilterOptions => _filterOptions;

    public IReadOnlyList<ResultRowViewModel> AllResults
    {
        get => _allResults;
        private set => SetProperty(ref _allResults, value);
    }

    public IReadOnlyList<ResultRowViewModel> VisibleResults
    {
        get => _visibleResults;
        private set => SetProperty(ref _visibleResults, value);
    }

    public ResultsFilter SelectedFilter
    {
        get => _selectedFilter;
        set
        {
            if (SetProperty(ref _selectedFilter, value))
            {
                ApplyFilter();
            }
        }
    }

    public ResultRowViewModel? SelectedResult
    {
        get => _selectedResult;
        set
        {
            if (value is null
                && _selectedResult is not null
                && ContainsResult(VisibleResults, _selectedResult.ResultId))
            {
                // WPF 在 ItemsSource 刷新期间会短暂回写 null；同一逻辑结果仍可见时忽略该框架瞬态。
                return;
            }

            var previousResultId = _selectedResult?.ResultId;
            if (!SetProperty(ref _selectedResult, value))
            {
                return;
            }

            if (!string.Equals(
                    previousResultId,
                    value?.ResultId,
                    StringComparison.Ordinal))
            {
                DiagnosticPreview = null;
                IsPreviewVisible = false;
            }
            RaiseActionProperties();
        }
    }

    public DiagnosticResultViewModel? DiagnosticPreview
    {
        get => _diagnosticPreview;
        private set => SetProperty(ref _diagnosticPreview, value);
    }

    public bool IsPreviewVisible
    {
        get => _isPreviewVisible;
        private set => SetProperty(ref _isPreviewVisible, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool CanLoadSelectedPreview =>
        !IsBusy && SelectedResult?.CanPreview == true;

    public string PreviewActionReason => SelectedResult switch
    {
        null => "请先选择一个结果。",
        { CanPreview: false } result => result.PreviewUnavailableReason,
        _ when IsBusy => "正在加载安全预览。",
        _ => "只读取固定诊断卡片，不显示路径、日志正文、Token 或网络信息。",
    };

    /// <summary>创建不依赖网络的确定性结果中心模型。</summary>
    public static ResultsPageViewModel CreateForSmokeTest(
        IReadOnlyList<TaskRecord> tasks) => new(tasks);

    /// <summary>保留筛选和选中结果，并应用最新 Session 快照。</summary>
    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ApplyTasks(snapshot.State.Tasks.Tasks);
    }

    /// <summary>加载当前结果的固定诊断合同；未知类型永不回退到通用内容预览。</summary>
    public async Task LoadSelectedPreviewAsync(CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能读取结果。");
        var selected = SelectedResult
            ?? throw new InvalidOperationException("请先选择结果。");
        if (!selected.CanPreview)
        {
            throw new InvalidOperationException(selected.PreviewUnavailableReason);
        }

        IsBusy = true;
        StatusMessage = $"正在读取结果 {selected.ResultId} 的安全预览……";
        try
        {
            var result = await session.GetDiagnosticResultAsync(
                selected.TaskId,
                cancellationToken).ConfigureAwait(true);
            DiagnosticPreview = DiagnosticResultViewModel.FromResult(result);
            IsPreviewVisible = true;
            StatusMessage = "安全预览已通过固定诊断合同校验。";
        }
        catch (Exception)
        {
            DiagnosticPreview = DiagnosticResultViewModel.FromError(
                "结果无法安全显示；详细信息已写入脱敏日志。");
            IsPreviewVisible = true;
            StatusMessage = "读取安全预览失败；结果元数据和任务状态未被修改。";
            throw;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplyTasks(IReadOnlyList<TaskRecord> tasks)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        var selectedResultId = SelectedResult?.ResultId;
        AllResults = tasks
            .Where(IsResultTask)
            .OrderByDescending(task => task.UpdatedAt)
            .Select(ResultRowViewModel.FromRecord)
            .ToArray();
        ApplyFilter();
        SelectedResult = ResolveSelection(VisibleResults, selectedResultId);
        StatusMessage = AllResults.Count == 0
            ? "Mac Core 当前没有可显示的任务结果。"
            : $"已加载 {AllResults.Count} 个安全结果元数据。";
    }

    private void ApplyFilter()
    {
        var selectedResultId = SelectedResult?.ResultId;
        VisibleResults = AllResults.Where(MatchesFilter).ToArray();
        SelectedResult = ResolveSelection(VisibleResults, selectedResultId);
    }

    private bool MatchesFilter(ResultRowViewModel result) => SelectedFilter switch
    {
        ResultsFilter.All => true,
        ResultsFilter.Diagnostic => string.Equals(
            result.TaskType,
            "system.diagnostic_snapshot",
            StringComparison.Ordinal),
        ResultsFilter.Archived => string.Equals(
            result.Status,
            "Archived",
            StringComparison.Ordinal),
        _ => false,
    };

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanLoadSelectedPreview));
        RaisePropertyChanged(nameof(PreviewActionReason));
    }

    private static bool IsResultTask(TaskRecord task) =>
        !string.IsNullOrWhiteSpace(task.ResultId)
        && task.Status is "Completed" or "Archived";

    private static bool ContainsResult(
        IReadOnlyList<ResultRowViewModel> results,
        string resultId)
    {
        for (var index = 0; index < results.Count; index++)
        {
            if (string.Equals(
                    results[index].ResultId,
                    resultId,
                    StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }

    private static ResultRowViewModel? ResolveSelection(
        IReadOnlyList<ResultRowViewModel> results,
        string? selectedResultId)
    {
        if (!string.IsNullOrWhiteSpace(selectedResultId))
        {
            for (var index = 0; index < results.Count; index++)
            {
                if (string.Equals(
                        results[index].ResultId,
                        selectedResultId,
                        StringComparison.Ordinal))
                {
                    return results[index];
                }
            }
        }

        return results.Count > 0 ? results[0] : null;
    }
}
