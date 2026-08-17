using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>耐久工作流控制页；动作仅调用固定 Workflow API。</summary>
public sealed class AutomationPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private IReadOnlyList<WorkflowRecord> _workflows = Array.Empty<WorkflowRecord>();
    private WorkflowRecord? _selectedWorkflow;
    private string _statusMessage = "工作流状态来自 Mac Core SQLite，执行仍由注册 Worker 完成。";
    private bool _isBusy;

    public AutomationPageViewModel(ControlCenterSession session) : base("自动化")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private AutomationPageViewModel(IReadOnlyList<WorkflowRecord> workflows) : base("自动化")
    {
        Workflows = workflows;
        SelectedWorkflow = workflows.Count > 0 ? workflows[0] : null;
    }

    public IReadOnlyList<WorkflowRecord> Workflows
    {
        get => _workflows;
        private set => SetProperty(ref _workflows, value);
    }

    public WorkflowRecord? SelectedWorkflow
    {
        get => _selectedWorkflow;
        set
        {
            if (SetProperty(ref _selectedWorkflow, value))
            {
                RaisePropertyChanged(nameof(SelectedSteps));
                RaiseActions();
            }
        }
    }

    public IReadOnlyList<WorkflowStepRecord> SelectedSteps =>
        SelectedWorkflow?.Steps ?? Array.Empty<WorkflowStepRecord>();

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

    // 操作可用性 --------------------------------------------------------------
    public bool CanRefresh => !IsBusy;
    public bool CanCreateSafeWorkflow => !IsBusy;
    public bool CanPause => !IsBusy && SelectedWorkflow?.Status is "Ready" or "Running" or "NeedsAttention";
    public bool CanResume => !IsBusy && SelectedWorkflow?.Status == "Paused";
    public bool CanCancel => !IsBusy && SelectedWorkflow?.Status is not null and not "Completed" and not "Cancelled" and not "Failed";
    public bool CanReconcile => !IsBusy && SelectedWorkflow?.Status is not null and not "Paused" and not "Completed" and not "Cancelled" and not "Failed";

    public string RefreshActionReason => IsBusy
        ? "工作流操作正在处理中，请稍候。"
        : "重新加载工作流列表。";

    public string CreateActionReason => IsBusy
        ? "工作流操作正在处理中，请稍候。"
        : "创建固定的本地诊断测试工作流，不允许自定义 task_type 或 shell 命令。";

    public string ReconcileActionReason => BuildWorkflowActionReason(
        CanReconcile,
        "推进所选工作流并刷新状态。",
        "当前工作流状态不需要或不允许推进。");

    public string PauseActionReason => BuildWorkflowActionReason(
        CanPause,
        "暂停所选工作流。",
        "只有准备中、运行中或需要注意的工作流可以暂停。");

    public string ResumeActionReason => BuildWorkflowActionReason(
        CanResume,
        "恢复所选工作流。",
        "只有已暂停的工作流可以恢复。");

    public string CancelActionReason => BuildWorkflowActionReason(
        CanCancel,
        "取消所选工作流。",
        "已完成、已取消或已失败的工作流不能再次取消。");

    public static AutomationPageViewModel CreateForSmokeTest(IReadOnlyList<WorkflowRecord> workflows) =>
        new(workflows);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (IsBusy)
        {
            return;
        }

        var session = RequireSession();
        IsBusy = true;
        try
        {
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            StatusMessage = Workflows.Count == 0
                ? "当前没有工作流；可创建固定的本地诊断测试工作流。"
                : $"已加载 {Workflows.Count} 个耐久工作流。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>创建固定安全测试流，不允许用户输入 task_type 或 shell 命令。</summary>
    public async Task CreateSafeDiagnosticWorkflowAsync(CancellationToken cancellationToken)
    {
        if (IsBusy)
        {
            return;
        }

        var session = RequireSession();
        IsBusy = true;
        try
        {
            var request = new WorkflowCreateRequest(
                ProjectId: null,
                Name: "平台诊断测试",
                Priority: 100,
                MaxConcurrency: 1,
                IdempotencyKey: $"windows-platform-smoke-{Guid.NewGuid():N}",
                Steps:
                [
                    new WorkflowStepCreateRequest(
                        StepKey: "diagnostic",
                        TaskType: "system.diagnostic_snapshot",
                        DependsOn: Array.Empty<string>(),
                        RequiredCapability: null,
                        Payload: new { schema_version = "1.0" },
                        MaxAttempts: 2,
                        TimeoutSeconds: 30),
                    new WorkflowStepCreateRequest(
                        StepKey: "verify",
                        TaskType: "system.noop",
                        DependsOn: ["diagnostic"],
                        RequiredCapability: null,
                        Payload: new { purpose = "workflow-continuation-smoke" },
                        MaxAttempts: 2,
                        TimeoutSeconds: 30),
                ]);
            var created = await session.CreateWorkflowAsync(request, cancellationToken).ConfigureAwait(false);
            await session.ReconcileWorkflowAsync(created.WorkflowId, cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            SelectedWorkflow = Workflows.FirstOrDefault(item => item.WorkflowId == created.WorkflowId);
            StatusMessage = "已创建固定本地诊断工作流；无云端调用。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public Task ReconcileSelectedAsync(CancellationToken cancellationToken) =>
        RunSelectedActionAsync("reconcile", cancellationToken);

    public Task PauseSelectedAsync(CancellationToken cancellationToken) =>
        RunSelectedActionAsync("pause", cancellationToken);

    public Task ResumeSelectedAsync(CancellationToken cancellationToken) =>
        RunSelectedActionAsync("resume", cancellationToken);

    public Task CancelSelectedAsync(CancellationToken cancellationToken) =>
        RunSelectedActionAsync("cancel", cancellationToken);

    private async Task RunSelectedActionAsync(string action, CancellationToken cancellationToken)
    {
        if (IsBusy)
        {
            return;
        }

        var selected = SelectedWorkflow ?? throw new InvalidOperationException("请先选择工作流。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = action switch
            {
                "reconcile" => await session.ReconcileWorkflowAsync(selected.WorkflowId, cancellationToken).ConfigureAwait(false),
                "pause" => await session.PauseWorkflowAsync(selected.WorkflowId, cancellationToken).ConfigureAwait(false),
                "resume" => await session.ResumeWorkflowAsync(selected.WorkflowId, cancellationToken).ConfigureAwait(false),
                "cancel" => await session.CancelWorkflowAsync(selected.WorkflowId, cancellationToken).ConfigureAwait(false),
                _ => throw new InvalidOperationException("未知工作流动作。"),
            };
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            SelectedWorkflow = Workflows.FirstOrDefault(item => item.WorkflowId == selected.WorkflowId);
            StatusMessage = $"工作流动作 {action} 已提交并刷新。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCoreAsync(ControlCenterSession session, CancellationToken cancellationToken)
    {
        var selectedId = SelectedWorkflow?.WorkflowId;
        Workflows = await session.GetWorkflowsAsync(cancellationToken).ConfigureAwait(false);
        SelectedWorkflow = Workflows.FirstOrDefault(item => item.WorkflowId == selectedId)
            ?? (Workflows.Count > 0 ? Workflows[0] : null);
    }

    private string BuildWorkflowActionReason(bool canRun, string readyText, string unavailableText)
    {
        if (IsBusy)
        {
            return "工作流操作正在处理中，请稍候。";
        }
        if (SelectedWorkflow is null)
        {
            return "请先选择一个工作流。";
        }
        return canRun ? readyText : unavailableText;
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanRefresh));
        RaisePropertyChanged(nameof(CanCreateSafeWorkflow));
        RaisePropertyChanged(nameof(CanPause));
        RaisePropertyChanged(nameof(CanResume));
        RaisePropertyChanged(nameof(CanCancel));
        RaisePropertyChanged(nameof(CanReconcile));
        RaisePropertyChanged(nameof(RefreshActionReason));
        RaisePropertyChanged(nameof(CreateActionReason));
        RaisePropertyChanged(nameof(ReconcileActionReason));
        RaisePropertyChanged(nameof(PauseActionReason));
        RaisePropertyChanged(nameof(ResumeActionReason));
        RaisePropertyChanged(nameof(CancelActionReason));
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");
}
