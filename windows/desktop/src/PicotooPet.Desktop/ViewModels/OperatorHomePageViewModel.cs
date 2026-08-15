using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式首页：只投影既有事实，并提供受控新任务向导入口。</summary>
public sealed class OperatorHomePageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private OperatorProjection _projection;
    private double? _cpuPercent;
    private double? _memoryPercent;
    private double? _diskPercent;

    public OperatorHomePageViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
        : base("首页")
    {
        _session    = session ?? throw new ArgumentNullException(nameof(session));
        _projection = OperatorProjection.FromSnapshot(snapshot);
    }

    private OperatorHomePageViewModel(ControlCenterSessionSnapshot snapshot)
        : base("首页")
    {
        _projection = OperatorProjection.FromSnapshot(snapshot);
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

    /// <summary>资源条使用 0 作为不可用时的安全绘制值；可见文本仍明确显示破折号。</summary>
    public double CpuPercent => _cpuPercent ?? 0d;
    public double MemoryPercent => _memoryPercent ?? 0d;
    public double DiskPercent => _diskPercent ?? 0d;
    public string CpuText => FormatMetric(_cpuPercent);
    public string MemoryText => FormatMetric(_memoryPercent);
    public string DiskText => FormatMetric(_diskPercent);

    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot) =>
        Projection = OperatorProjection.FromSnapshot(snapshot);

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

    public NewTaskWizardViewModel CreateNewTaskWizard() =>
        _session is null
            ? NewTaskWizardViewModel.CreateForSmokeTest()
            : new NewTaskWizardViewModel(_session, _session.Snapshot);

    public static OperatorHomePageViewModel CreateForSmokeTest(
        ControlCenterSessionSnapshot snapshot) => new(snapshot);

    private static string FormatMetric(double? value) =>
        value is null
            ? "—"
            : $"{Math.Round(value.Value):0}%";

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
