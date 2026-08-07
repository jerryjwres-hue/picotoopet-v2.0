using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>云端开发合同页中的阶段状态。</summary>
public sealed record CloudDevelopmentMilestone(
    string Phase,
    string Status,
    string Description);

/// <summary>Handoff 准备、预览、最近记录和审批提交的原生 Phase 10A 页面模型。</summary>
public sealed class CloudDevelopmentPageViewModel : PageViewModel
{
    private const string DefaultTemplateId = "picotoopet-repo-maintenance-v1";
    private const string CodexTemplateId   = "picotoopet-repo-maintenance-codex-v1";
    private const int MaxTitleLength        = 120;
    private const int MaxObjectiveLength    = 1000;

    private static readonly IReadOnlyList<string> DefaultTrustChain =
        Array.AsReadOnly(
        [
            "Mac Handoff Manager",
            "Approval Center",
            "Windows Dev Broker",
            "Provider Adapter",
            "Isolated Worktree / Sandbox",
            "Return Package",
            "Local Validation",
            "Human Review",
            "PR / Merge / Release Approval",
        ]);

    private static readonly IReadOnlyList<string> DefaultSecurityBoundaries =
        Array.AsReadOnly(
        [
            "Protected 原件不得进入 Handoff Package，也不得上传给 Provider。",
            "Provider 返回内容默认不可信，必须通过本地验证和人工评审。",
            "禁止自动 push、merge、tag 或 release；发布需要独立人工批准。",
            "Provider 不得直接编辑 main 或 protected branch，也不得访问未批准目录。",
            "密钥不得写入命令行、Package、日志或返回文件。",
        ]);

    private static readonly IReadOnlyList<CloudDevelopmentMilestone> DefaultMilestones =
        Array.AsReadOnly(
        [
            new CloudDevelopmentMilestone(
                "Phase 2.3",
                "已完成",
                "Handoff / Return Contract v1 已冻结并通过解释性原生页面公开。"),
            new CloudDevelopmentMilestone(
                "Phase 10A",
                "当前可用",
                "准备固定模板 Handoff、查看安全摘要并提交 digest 绑定审批。"),
            new CloudDevelopmentMilestone(
                "Phase 10B",
                "未实施",
                "未来才实现 Windows Dev Broker、Provider 会话、事件流和 Return 本地校验。"),
        ]);

    private static readonly HandoffTemplateRecord SmokeTemplate = new(
        DefaultTemplateId,
        "PicotooPet 仓库维护",
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase23-slice-d-diagnostic-snapshot-release",
        "5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb");

    private readonly IHandoffGateway? _gateway;
    private IReadOnlyList<HandoffTemplateRecord> _templateOptions;
    private HandoffTemplateRecord? _selectedTemplate;
    private IReadOnlyList<HandoffRecord> _recentHandoffs;
    private HandoffRecord? _selectedRecentHandoff;
    private HandoffRecord? _selectedHandoff;
    private string _draftTitle = string.Empty;
    private string _draftObjective = string.Empty;
    private string _statusMessage = "Phase 10A 只准备和审批 Handoff，不启动 Provider。";
    private bool _isPreviewVisible;
    private bool _isBusy;
    private bool _isLoaded;

    /// <summary>创建无需网络的确定性页面，用于设计时和 smoke 测试。</summary>
    public CloudDevelopmentPageViewModel()
        : this(gateway: null, initializeSmoke: true)
    {
    }

    /// <summary>创建绑定 Mac Core Handoff 网关的运行时页面。</summary>
    public CloudDevelopmentPageViewModel(IHandoffGateway gateway)
        : this(
            gateway ?? throw new ArgumentNullException(nameof(gateway)),
            initializeSmoke: false)
    {
    }

    private CloudDevelopmentPageViewModel(
        IHandoffGateway? gateway,
        bool initializeSmoke)
        : base("云端开发")
    {
        _gateway          = gateway;
        _templateOptions  = Array.Empty<HandoffTemplateRecord>();
        _recentHandoffs   = Array.Empty<HandoffRecord>();
        RefreshCommand    = new AsyncRelayCommand(
            () => RefreshAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy);
        PrepareCommand    = new AsyncRelayCommand(
            () => PrepareAsync(CancellationToken.None),
            HandleCommandError,
            () => CanPrepare);
        SubmitCommand     = new AsyncRelayCommand(
            () => SubmitSelectedApprovalAsync(CancellationToken.None),
            HandleCommandError,
            () => CanSubmitApproval);

        if (initializeSmoke)
        {
            TemplateOptions  = [SmokeTemplate];
            SelectedTemplate = SmokeTemplate;
            IsLoaded         = true;
        }
    }

    public string ContractVersion => "1.0.0";

    public string ContractStatus => "Approved / Frozen";

    public bool ProviderConfigured => false;

    public string ProviderStatus =>
        "Provider 未安装、未配置、未调用；Phase 10A 不创建外部执行会话。";

    public string CurrentDelivery =>
        "Phase 10A：固定模板 Handoff 准备、安全预览和 digest 绑定审批。";

    public IReadOnlyList<string> TrustChain => DefaultTrustChain;

    public IReadOnlyList<string> SecurityBoundaries => DefaultSecurityBoundaries;

    public IReadOnlyList<CloudDevelopmentMilestone> PhaseMilestones => DefaultMilestones;

    public AsyncRelayCommand RefreshCommand { get; }

    public AsyncRelayCommand PrepareCommand { get; }

    public AsyncRelayCommand SubmitCommand { get; }

    public IReadOnlyList<HandoffTemplateRecord> TemplateOptions
    {
        get => _templateOptions;
        private set => SetProperty(ref _templateOptions, value);
    }

    public HandoffTemplateRecord? SelectedTemplate
    {
        get => _selectedTemplate;
        set
        {
            if (SetProperty(ref _selectedTemplate, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public string DraftTitle
    {
        get => _draftTitle;
        set
        {
            if (SetProperty(ref _draftTitle, value ?? string.Empty))
            {
                RaiseActionProperties();
            }
        }
    }

    public string DraftObjective
    {
        get => _draftObjective;
        set
        {
            if (SetProperty(ref _draftObjective, value ?? string.Empty))
            {
                RaiseActionProperties();
            }
        }
    }

    public IReadOnlyList<HandoffRecord> RecentHandoffs
    {
        get => _recentHandoffs;
        private set => SetProperty(ref _recentHandoffs, value);
    }

    public HandoffRecord? SelectedRecentHandoff
    {
        get => _selectedRecentHandoff;
        set
        {
            if (!SetProperty(ref _selectedRecentHandoff, value))
            {
                return;
            }
            if (value is not null)
            {
                SelectedHandoff  = value;
                IsPreviewVisible = true;
                StatusMessage    = "已加载固定 Handoff 安全投影；不显示路径正文、命令或凭据。";
            }
        }
    }

    /// <summary>当前显示的固定安全预览；与列表选择分离以抵御 ItemsSource 刷新。</summary>
    public HandoffRecord? SelectedHandoff
    {
        get => _selectedHandoff;
        private set
        {
            if (SetProperty(ref _selectedHandoff, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public bool IsPreviewVisible
    {
        get => _isPreviewVisible;
        private set => SetProperty(ref _isPreviewVisible, value);
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
                RaiseActionProperties();
            }
        }
    }

    public bool IsLoaded
    {
        get => _isLoaded;
        private set => SetProperty(ref _isLoaded, value);
    }

    public string InputValidationMessage
    {
        get
        {
            var title     = DraftTitle.Trim();
            var objective = DraftObjective.Trim();
            if (SelectedTemplate is null)
            {
                return "正在等待 Mac Core 发布固定模板。";
            }
            if (title.Length == 0)
            {
                return "请输入任务标题。";
            }
            if (title.Length > MaxTitleLength)
            {
                return $"标题不能超过 {MaxTitleLength} 个字符。";
            }
            if (objective.Length == 0)
            {
                return "请输入目标摘要。";
            }
            if (objective.Length > MaxObjectiveLength)
            {
                return $"目标摘要不能超过 {MaxObjectiveLength} 个字符。";
            }
            return "输入有效；路径、命令、仓库和 Provider 参数由固定模板提供。";
        }
    }

    public bool CanPrepare =>
        !IsBusy
        && SelectedTemplate is not null
        && DraftTitle.Trim().Length is > 0 and <= MaxTitleLength
        && DraftObjective.Trim().Length is > 0 and <= MaxObjectiveLength;

    public bool CanSubmitApproval =>
        !IsBusy
        && SelectedHandoff is { Status: "prepared" };

    /// <summary>首次打开时并发读取模板与最近 Handoff。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在读取固定模板和最近 Handoff……";
        try
        {
            var templatesTask = _gateway.GetTemplatesAsync(cancellationToken);
            var handoffsTask  = _gateway.GetHandoffsAsync(cancellationToken);
            await Task.WhenAll(templatesTask, handoffsTask).ConfigureAwait(true);
            ApplyTemplates(await templatesTask.ConfigureAwait(true));
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            IsLoaded      = true;
            StatusMessage = $"已加载 {RecentHandoffs.Count} 条 Handoff 安全记录。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "加载失败；现有输入和安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>重新读取最近记录；同一逻辑预览不会因列表对象替换而消失。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在刷新 Handoff 状态……";
        try
        {
            var records = await _gateway.GetHandoffsAsync(cancellationToken)
                .ConfigureAwait(true);
            ApplyHandoffs(records);
            IsLoaded      = true;
            StatusMessage = $"已刷新 {records.Length} 条记录；已有安全预览保持可见。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "刷新失败；已有安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>使用一次生成的幂等键准备 Handoff，并对瞬态网络错误最多重试一次。</summary>
    public async Task PrepareAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能准备 Handoff。");
        var template = SelectedTemplate
            ?? throw new InvalidOperationException("Mac Core 尚未发布固定 Handoff 模板。");
        if (!CanPrepare)
        {
            throw new InvalidOperationException(InputValidationMessage);
        }

        var request = new HandoffPrepareRequest(
            template.TemplateId,
            DraftTitle.Trim(),
            DraftObjective.Trim(),
            ExpiresSeconds: 1800);
        var idempotencyKey = $"windows-handoff-prepare-{Guid.NewGuid():N}";
        IsBusy        = true;
        StatusMessage = "正在生成确定性摘要和安全预览……";
        try
        {
            HandoffRecord prepared;
            try
            {
                prepared = await gateway.PrepareAsync(
                    request,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            catch (ApiException exception) when (exception.Retryable)
            {
                StatusMessage = "网络暂时不可用，正在使用同一幂等键重试一次……";
                prepared = await gateway.PrepareAsync(
                    request,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            UpsertAndSelect(prepared);
            IsLoaded      = true;
            StatusMessage = "Handoff 已准备；请核对摘要后提交到审批中心。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>把当前 prepared 摘要提交审批；本动作不启动 Provider 或任务队列。</summary>
    public async Task SubmitSelectedApprovalAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能提交审批。");
        var selected = SelectedHandoff
            ?? throw new InvalidOperationException("请先准备或选择一个 Handoff。");
        if (!CanSubmitApproval)
        {
            throw new InvalidOperationException("只有 prepared Handoff 可以提交审批。");
        }

        var idempotencyKey =
            $"windows-handoff-submit-{selected.HandoffId}-{Guid.NewGuid():N}";
        IsBusy        = true;
        StatusMessage = "正在提交 digest 绑定审批……";
        try
        {
            HandoffRecord submitted;
            try
            {
                submitted = await gateway.SubmitApprovalAsync(
                    selected.HandoffId,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            catch (ApiException exception) when (exception.Retryable)
            {
                StatusMessage = "网络暂时不可用，正在使用同一幂等键重试一次……";
                submitted = await gateway.SubmitApprovalAsync(
                    selected.HandoffId,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            UpsertAndSelect(submitted);
            StatusMessage = "已提交审批；请到“审批”页面核对 request digest 后决定。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplyTemplates(IReadOnlyList<HandoffTemplateRecord> templates)
    {
        ArgumentNullException.ThrowIfNull(templates);
        var safe = templates
            .Where(item =>
                (string.Equals(item.TemplateId, DefaultTemplateId, StringComparison.Ordinal)
                 && string.Equals(item.Provider, "manual", StringComparison.Ordinal))
                || (string.Equals(item.TemplateId, CodexTemplateId, StringComparison.Ordinal)
                    && string.Equals(item.Provider, "codex", StringComparison.Ordinal)))
            .OrderBy(item => string.Equals(
                item.TemplateId,
                DefaultTemplateId,
                StringComparison.Ordinal) ? 0 : 1)
            .ToArray();
        TemplateOptions = safe;
        SelectedTemplate = safe.FirstOrDefault(item =>
                string.Equals(
                    item.TemplateId,
                    SelectedTemplate?.TemplateId,
                    StringComparison.Ordinal))
            ?? safe.FirstOrDefault(item =>
                string.Equals(item.TemplateId, DefaultTemplateId, StringComparison.Ordinal))
            ?? safe.FirstOrDefault();
    }

    private void ApplyHandoffs(IReadOnlyList<HandoffRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var previousPreview = SelectedHandoff;
        var selectedId      = previousPreview?.HandoffId;
        var ordered = records
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        RecentHandoffs = ordered;

        if (selectedId is null)
        {
            SelectedRecentHandoff = ordered.FirstOrDefault();
            return;
        }

        var refreshed = ordered.FirstOrDefault(item =>
            string.Equals(item.HandoffId, selectedId, StringComparison.Ordinal));
        if (refreshed is null)
        {
            SelectedRecentHandoff = ordered.FirstOrDefault();
            return;
        }

        if (previousPreview is not null && PreviewEquivalent(previousPreview, refreshed))
        {
            _selectedRecentHandoff = refreshed;
            RaisePropertyChanged(nameof(SelectedRecentHandoff));
            SelectedHandoff  = previousPreview;
            IsPreviewVisible = true;
            return;
        }

        SelectedRecentHandoff = refreshed;
    }

    private void UpsertAndSelect(HandoffRecord record)
    {
        var records = RecentHandoffs
            .Where(item => !string.Equals(
                item.HandoffId,
                record.HandoffId,
                StringComparison.Ordinal))
            .Append(record)
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        RecentHandoffs        = records;
        SelectedRecentHandoff = record;
        SelectedHandoff       = record;
        IsPreviewVisible      = true;
    }

    private static bool PreviewEquivalent(HandoffRecord left, HandoffRecord right) =>
        string.Equals(left.HandoffId, right.HandoffId, StringComparison.Ordinal)
        && string.Equals(left.Status, right.Status, StringComparison.Ordinal)
        && string.Equals(left.RequestDigest, right.RequestDigest, StringComparison.Ordinal)
        && string.Equals(left.PackageDigest, right.PackageDigest, StringComparison.Ordinal)
        && string.Equals(left.ApprovalId, right.ApprovalId, StringComparison.Ordinal);

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(InputValidationMessage));
        RaisePropertyChanged(nameof(CanPrepare));
        RaisePropertyChanged(nameof(CanSubmitApproval));
        RefreshCommand.NotifyCanExecuteChanged();
        PrepareCommand.NotifyCanExecuteChanged();
        SubmitCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception)
    {
        StatusMessage = FormatError(
            "操作失败；现有输入和安全预览已保留。",
            exception);
    }

    private static bool IsBoundedOperationalError(Exception exception) =>
        exception is ApiException
            or InvalidOperationException
            or IOException;

    private static string FormatError(string prefix, Exception exception)
    {
        var message = exception.Message.Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (message.Length > 180)
        {
            message = message[..180] + "…";
        }
        return string.IsNullOrWhiteSpace(message)
            ? prefix
            : $"{prefix} {message}";
    }
}
