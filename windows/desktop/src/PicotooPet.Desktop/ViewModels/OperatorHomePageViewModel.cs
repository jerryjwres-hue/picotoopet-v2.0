using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式首页：只投影既有事实，并提供受控新任务向导与闭集工作组件。</summary>
public sealed class OperatorHomePageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private readonly OperatorWidgetLayoutStore? _widgetLayoutStore;
    private OperatorProjection _projection;
    private ControlCenterSessionSnapshot _snapshot;
    private OperatorWidgetLayout _widgetLayout;
    private string _widgetLayoutMessage = "拖动式插件暂不开放；可安全调整固定组件的显示和顺序。";

    public OperatorHomePageViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot,
        OperatorWidgetLayoutStore? widgetLayoutStore = null)
        : base("首页")
    {
        _session           = session ?? throw new ArgumentNullException(nameof(session));
        _snapshot          = snapshot ?? throw new ArgumentNullException(nameof(snapshot));
        _projection        = OperatorProjection.FromSnapshot(snapshot);
        _widgetLayoutStore = widgetLayoutStore ?? OperatorWidgetLayoutStore.CreateForCurrentUser();
        _widgetLayout      = _widgetLayoutStore.LoadOrDefault();
    }

    private OperatorHomePageViewModel(ControlCenterSessionSnapshot snapshot)
        : base("首页")
    {
        _snapshot     = snapshot ?? throw new ArgumentNullException(nameof(snapshot));
        _projection   = OperatorProjection.FromSnapshot(snapshot);
        _widgetLayout = OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
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
    public IReadOnlyList<OperatorTaskCard> RecentTasks => Projection.PendingReview
        .Concat(Projection.InProgress)
        .Concat(Projection.Completed)
        .OrderByDescending(card => card.UpdatedAt)
        .Take(6)
        .ToArray();

    public int PendingReviewCount => Projection.PendingReview.Count;
    public int InProgressCount => Projection.InProgress.Count;
    public int CompletedCount => Projection.Completed.Count;
    public string CoreStatus => Projection.CoreStatus;
    public string WorkerStatus => Projection.WorkerStatus;
    public string WindowsStatus => Projection.WindowsStatus;
    public string SystemSummary => Projection.SystemSummary;

    /// <summary>左侧和首页只共用这一份助手状态解析，避免重复状态源。</summary>
    public string AssistantStateKey =>
        OperatorAssistantStateResolver.ToKey(OperatorAssistantStateResolver.FromSnapshot(_snapshot));

    public string AssistantTitle =>
        OperatorAssistantStateResolver.ToTitle(OperatorAssistantStateResolver.FromSnapshot(_snapshot));

    public string AssistantSubtitle =>
        OperatorAssistantStateResolver.ToSubtitle(OperatorAssistantStateResolver.FromSnapshot(_snapshot));

    /// <summary>只返回当前用户选择显示的固定组件；未知 ID 永远不会进入这里。</summary>
    public IReadOnlyList<OperatorWidgetCard> Widgets
    {
        get
        {
            var hidden = new HashSet<string>(_widgetLayout.HiddenWidgetIds, StringComparer.Ordinal);
            return BuildWidgetCards()
                .Where(widget => !hidden.Contains(widget.Id))
                .ToArray();
        }
    }

    /// <summary>组件管理只允许固定目录的显隐和顺序调整。</summary>
    public IReadOnlyList<OperatorWidgetOption> WidgetOptions
    {
        get
        {
            var hidden = new HashSet<string>(_widgetLayout.HiddenWidgetIds, StringComparer.Ordinal);
            var byId   = OperatorWidgetCatalog.CreateDefault()
                .ToDictionary(widget => widget.Id, StringComparer.Ordinal);
            return _widgetLayout.WidgetIds
                .Where(byId.ContainsKey)
                .Select(widgetId =>
                {
                    var descriptor = byId[widgetId];
                    return new OperatorWidgetOption(
                        descriptor.Id,
                        descriptor.Title,
                        descriptor.Description,
                        IsVisible: !hidden.Contains(descriptor.Id),
                        descriptor.IsAvailable,
                        descriptor.AvailabilityText);
                })
                .ToArray();
        }
    }

    public string WidgetLayoutMessage
    {
        get => _widgetLayoutMessage;
        private set => SetProperty(ref _widgetLayoutMessage, value);
    }

    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        _snapshot = snapshot ?? throw new ArgumentNullException(nameof(snapshot));
        Projection = OperatorProjection.FromSnapshot(snapshot);
        RaisePropertyChanged(nameof(AssistantStateKey));
        RaisePropertyChanged(nameof(AssistantTitle));
        RaisePropertyChanged(nameof(AssistantSubtitle));
        RaisePropertyChanged(nameof(Widgets));
    }

    /// <summary>切换固定组件显隐；Search 即使显示也仍保持“尚未接入”，不能执行。</summary>
    public void ToggleWidget(string widgetId)
    {
        if (!OperatorWidgetCatalog.Contains(widgetId))
        {
            WidgetLayoutMessage = "未知组件已被安全拒绝。";
            return;
        }

        var hidden = new HashSet<string>(_widgetLayout.HiddenWidgetIds, StringComparer.Ordinal);
        if (!hidden.Add(widgetId))
        {
            hidden.Remove(widgetId);
        }

        _widgetLayout = OperatorWidgetLayout.Normalize(_widgetLayout.WidgetIds, hidden);
        PersistWidgetLayout();
        RaiseWidgetLayoutProperties();
    }

    /// <summary>使用确定性的上移/下移代替任意拖拽脚本，降低布局状态损坏风险。</summary>
    public void MoveWidget(string widgetId, int offset)
    {
        if (!OperatorWidgetCatalog.Contains(widgetId) || offset == 0)
        {
            return;
        }

        var ordered = _widgetLayout.WidgetIds.ToList();
        var current = ordered.IndexOf(widgetId);
        if (current < 0)
        {
            return;
        }

        var target = Math.Clamp(current + Math.Sign(offset), 0, ordered.Count - 1);
        if (target == current)
        {
            return;
        }

        (ordered[current], ordered[target]) = (ordered[target], ordered[current]);
        _widgetLayout = OperatorWidgetLayout.Normalize(ordered, _widgetLayout.HiddenWidgetIds);
        PersistWidgetLayout();
        RaiseWidgetLayoutProperties();
    }

    public NewTaskWizardViewModel CreateNewTaskWizard() =>
        _session is null
            ? NewTaskWizardViewModel.CreateForSmokeTest()
            : new NewTaskWizardViewModel(_session, _session.Snapshot);

    public static OperatorHomePageViewModel CreateForSmokeTest(
        ControlCenterSessionSnapshot snapshot) => new(snapshot);

    private OperatorWidgetCard[] BuildWidgetCards()
    {
        var descriptors = OperatorWidgetCatalog.CreateDefault()
            .ToDictionary(widget => widget.Id, StringComparer.Ordinal);
        var runningTasks = _snapshot.State.Tasks.Tasks
            .Where(task => string.Equals(task.Status, "Running", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var queuedTasks = _snapshot.State.Tasks.Tasks
            .Where(task => string.Equals(task.Status, "Queued", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var hasBusinessAnalysisRunning = runningTasks.Any(task =>
            string.Equals(task.TaskType, "business.local_intelligence.v1", StringComparison.Ordinal));
        var hasBusinessAnalysisQueued = queuedTasks.Any(task =>
            string.Equals(task.TaskType, "business.local_intelligence.v1", StringComparison.Ordinal));
        var hasVideoTaskRunning = runningTasks.Any(task =>
            task.TaskType.Contains("video", StringComparison.OrdinalIgnoreCase));
        var hasVideoTaskQueued = queuedTasks.Any(task =>
            task.TaskType.Contains("video", StringComparison.OrdinalIgnoreCase));
        var hasCreativeTaskRunning = runningTasks.Any(task =>
            string.Equals(task.TaskType, "creative.content_plan.v1", StringComparison.Ordinal));
        var hasCreativeTaskQueued = queuedTasks.Any(task =>
            string.Equals(task.TaskType, "creative.content_plan.v1", StringComparison.Ordinal));
        var hasResult = Projection.Completed.Any(card => card.HasResult);

        return _widgetLayout.WidgetIds
            .Where(descriptors.ContainsKey)
            .Select(widgetId =>
            {
                var descriptor = descriptors[widgetId];
                var state = widgetId switch
                {
                    "search-insight" => ("尚未接入", "Disabled"),
                    "comment-analysis" when hasBusinessAnalysisRunning => ("分析中", "Active"),
                    "comment-analysis" when hasBusinessAnalysisQueued => ("等待执行", "Ready"),
                    "comment-analysis" => ("可用", "Ready"),
                    "video-creation" when hasVideoTaskRunning => ("创作中", "Active"),
                    "video-creation" when hasVideoTaskQueued => ("已排队", "Ready"),
                    "video-creation" => ("等待任务", "Ready"),
                    "content-generation" when hasCreativeTaskRunning => ("创作中", "Active"),
                    "content-generation" when hasCreativeTaskQueued => ("等待执行", "Ready"),
                    "content-generation" => ("可用", "Ready"),
                    "result-optimization" when hasResult => ("有新结果", "Success"),
                    "result-optimization" => ("等待结果", "Ready"),
                    _ => (descriptor.AvailabilityText, descriptor.IsAvailable ? "Ready" : "Disabled"),
                };
                return new OperatorWidgetCard(
                    descriptor.Id,
                    descriptor.Title,
                    descriptor.Description,
                    descriptor.Glyph,
                    descriptor.IsAvailable,
                    state.Item1,
                    state.Item2);
            })
            .ToArray();
    }

    private void PersistWidgetLayout()
    {
        if (_widgetLayoutStore is null)
        {
            WidgetLayoutMessage = "本次会话的工作台布局已更新。";
            return;
        }

        WidgetLayoutMessage = _widgetLayoutStore.TrySave(_widgetLayout)
            ? "工作台布局已保存。"
            : "布局保存失败，已保留当前会话设置；其他功能不受影响。";
    }

    private void RaiseWidgetLayoutProperties()
    {
        RaisePropertyChanged(nameof(Widgets));
        RaisePropertyChanged(nameof(WidgetOptions));
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
        RaisePropertyChanged(nameof(Widgets));
    }
}
