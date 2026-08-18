using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>平台健康页展示 Core/DB/Queue/Worker capability 的结构化事实。</summary>
public sealed class HealthPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private AutomationHealthResponse? _snapshot;
    private string _statusMessage = "尚未读取平台健康快照。";
    private bool _isBusy;

    public HealthPageViewModel(ControlCenterSession session) : base("健康")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private HealthPageViewModel(AutomationHealthResponse snapshot) : base("健康")
    {
        Snapshot = snapshot;
    }

    public AutomationHealthResponse? Snapshot
    {
        get => _snapshot;
        private set
        {
            if (SetProperty(ref _snapshot, value))
            {
                RaisePropertyChanged(nameof(WorkflowSummary));
                RaisePropertyChanged(nameof(TaskSummary));
                RaisePropertyChanged(nameof(Capabilities));
                RaisePropertyChanged(nameof(DatabaseSchemaText));
            }
        }
    }

    public IReadOnlyList<CapabilityRegistrationRecord> Capabilities =>
        Snapshot?.Capabilities ?? Array.Empty<CapabilityRegistrationRecord>();

    public string WorkflowSummary => FormatCounts(Snapshot?.WorkflowCounts);
    public string TaskSummary => FormatCounts(Snapshot?.TaskCounts);
    public string DatabaseSchemaText => Snapshot is null ? "—" : $"Migration {Snapshot.DatabaseSchemaVersion}";

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
                RaisePropertyChanged(nameof(CanRefresh));
                RaisePropertyChanged(nameof(RefreshActionReason));
            }
        }
    }

    // 操作可用性 --------------------------------------------------------------
    public bool CanRefresh => !IsBusy;

    public string RefreshActionReason => IsBusy
        ? "健康快照正在刷新，请稍候。"
        : "重新读取数据库、任务、工作流和 Worker capability 的结构化健康事实。";

    public static HealthPageViewModel CreateForSmokeTest(AutomationHealthResponse snapshot) =>
        new(snapshot);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy)
        {
            return;
        }

        var session = _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");
        IsBusy = true;
        try
        {
            Snapshot = await session.GetAutomationHealthAsync(cancellationToken).ConfigureAwait(false);
            StatusMessage = $"健康快照更新时间：{Snapshot.ObservedAt.LocalDateTime:yyyy-MM-dd HH:mm:ss}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private static string FormatCounts(Dictionary<string, int>? counts) =>
        counts is null || counts.Count == 0
            ? "无记录"
            : string.Join(" · ", counts.OrderBy(item => item.Key).Select(item => $"{item.Key} {item.Value}"));
}