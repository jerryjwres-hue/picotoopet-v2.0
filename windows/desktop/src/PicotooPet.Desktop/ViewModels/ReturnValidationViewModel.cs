using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 10B-A approved Handoff、Return 演练和安全预览状态。</summary>
public sealed class ReturnValidationViewModel : ObservableObject
{
    private readonly IReturnGateway? _gateway;
    private IReadOnlyList<HandoffRecord> _approvedHandoffs;
    private HandoffRecord? _selectedHandoff;
    private IReadOnlyList<ReturnRecord> _recentReturns;
    private ReturnRecord? _selectedRecentReturn;
    private ReturnRecord? _selectedReturn;
    private string _statusMessage;
    private bool _isPreviewVisible;
    private bool _isBusy;

    /// <summary>创建无需网络的确定性 Return 面板，用于设计时和真实 WPF 布局测试。</summary>
    public ReturnValidationViewModel()
        : this(gateway: null, initializeSmoke: true)
    {
    }

    /// <summary>创建绑定 Mac Core Return 受限网关的运行时模型。</summary>
    public ReturnValidationViewModel(IReturnGateway gateway)
        : this(
            gateway ?? throw new ArgumentNullException(nameof(gateway)),
            initializeSmoke: false)
    {
    }

    private ReturnValidationViewModel(
        IReturnGateway? gateway,
        bool initializeSmoke)
    {
        _gateway           = gateway;
        _approvedHandoffs  = Array.Empty<HandoffRecord>();
        _recentReturns     = Array.Empty<ReturnRecord>();
        _statusMessage     = "Phase 10B-A 只验证本地 Return 合同，不启动 Provider。";
        RefreshCommand     = new AsyncRelayCommand(
            () => RefreshAsync(CancellationToken.None),
            HandleCommandError,
            () => !IsBusy);
        RunSelfTestCommand = new AsyncRelayCommand(
            () => RunReturnSelfTestAsync(CancellationToken.None),
            HandleCommandError,
            () => CanRunReturnSelfTest);

        if (initializeSmoke)
        {
            var handoff = CreateSmokeHandoff();
            var result  = CreateSmokeReturn();
            ApprovedHandoffs   = [handoff];
            SelectedHandoff    = handoff;
            RecentReturns      = [result];
            SelectedRecentReturn = result;
            SelectedReturn     = result;
            IsPreviewVisible   = true;
        }
    }

    /// <summary>本切片不会执行 Provider、代码、测试、构建或 Git 写操作。</summary>
    public string SafetyNotice =>
        "仅运行服务器自有的零变更 Return 合同演练；不上传文件、不启动 Provider、"
        + "不运行代码/测试/构建、不应用 diff、不修改 worktree 或 Git。";

    public AsyncRelayCommand RefreshCommand { get; }

    public AsyncRelayCommand RunSelfTestCommand { get; }

    public IReadOnlyList<HandoffRecord> ApprovedHandoffs
    {
        get => _approvedHandoffs;
        private set => SetProperty(ref _approvedHandoffs, value);
    }

    public HandoffRecord? SelectedHandoff
    {
        get => _selectedHandoff;
        set
        {
            if (value is null && _selectedHandoff is not null)
            {
                // ItemsSource 替换时的瞬时 null 不是用户取消选择，不清空 approved Handoff。
                return;
            }
            if (SetProperty(ref _selectedHandoff, value))
            {
                RaiseActionProperties();
            }
        }
    }

    public IReadOnlyList<ReturnRecord> RecentReturns
    {
        get => _recentReturns;
        private set => SetProperty(ref _recentReturns, value);
    }

    public ReturnRecord? SelectedRecentReturn
    {
        get => _selectedRecentReturn;
        set
        {
            if (value is null && _selectedRecentReturn is not null)
            {
                // ListBox 在 ItemsSource 替换时会短暂回写 null；保留当前逻辑预览。
                return;
            }
            if (!SetProperty(ref _selectedRecentReturn, value))
            {
                return;
            }
            if (value is not null)
            {
                SelectedReturn   = value;
                IsPreviewVisible = true;
                StatusMessage    = "已加载固定 Return 安全投影；不显示文件正文、路径或原始日志。";
            }
        }
    }

    /// <summary>与列表选择分离的固定 Return 预览，用于抵御 ItemsSource 替换。</summary>
    public ReturnRecord? SelectedReturn
    {
        get => _selectedReturn;
        private set => SetProperty(ref _selectedReturn, value);
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

    public bool CanRunReturnSelfTest =>
        !IsBusy
        && _gateway is not null
        && SelectedHandoff is { Status: "approved" };

    /// <summary>首次打开时并发读取 approved Handoff 和最近 Return 安全投影。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在读取 approved Handoff 和最近 Return……";
        try
        {
            var handoffsTask = _gateway.GetHandoffsAsync(cancellationToken);
            var returnsTask  = _gateway.GetReturnsAsync(cancellationToken);
            await Task.WhenAll(handoffsTask, returnsTask).ConfigureAwait(true);
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            ApplyReturns(await returnsTask.ConfigureAwait(true));
            StatusMessage =
                $"已加载 {ApprovedHandoffs.Count} 条 approved Handoff 和 {RecentReturns.Count} 条 Return。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "加载失败；已有 Return 安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>刷新 Handoff 与 Return；同一 return_id 的等价预览对象保持不变。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        if (_gateway is null || IsBusy)
        {
            return;
        }

        IsBusy        = true;
        StatusMessage = "正在刷新 Return 合同状态……";
        try
        {
            var handoffsTask = _gateway.GetHandoffsAsync(cancellationToken);
            var returnsTask  = _gateway.GetReturnsAsync(cancellationToken);
            await Task.WhenAll(handoffsTask, returnsTask).ConfigureAwait(true);
            ApplyHandoffs(await handoffsTask.ConfigureAwait(true));
            ApplyReturns(await returnsTask.ConfigureAwait(true));
            StatusMessage = "Return 状态已刷新；已有安全预览保持可见。";
        }
        catch (Exception exception) when (IsBoundedOperationalError(exception))
        {
            StatusMessage = FormatError(
                "刷新失败；已有 Return 安全预览已保留。",
                exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>使用一次生成的幂等键运行本地演练，并对瞬态错误最多重试一次。</summary>
    public async Task RunReturnSelfTestAsync(CancellationToken cancellationToken)
    {
        var gateway = _gateway
            ?? throw new InvalidOperationException("Smoke test 模式不能运行 Return 演练。");
        var handoff = SelectedHandoff
            ?? throw new InvalidOperationException("请先选择一个 approved Handoff。");
        if (!CanRunReturnSelfTest)
        {
            throw new InvalidOperationException("只有 approved Handoff 可以运行 Return 合同验证。");
        }

        var idempotencyKey =
            $"windows-return-self-test-{handoff.HandoffId}-{Guid.NewGuid():N}";
        IsBusy        = true;
        StatusMessage = "正在运行服务器自有的零变更 Return 合同演练……";
        try
        {
            ReturnRecord validated;
            try
            {
                validated = await gateway.RunReturnSelfTestAsync(
                    handoff.HandoffId,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            catch (ApiException exception) when (exception.Retryable)
            {
                StatusMessage = "网络暂时不可用，正在使用同一幂等键重试一次……";
                validated = await gateway.RunReturnSelfTestAsync(
                    handoff.HandoffId,
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            UpsertAndSelect(validated);
            StatusMessage = validated.Status switch
            {
                "contract_validated" =>
                    "Return 合同验证通过；尚未运行 Provider、代码、测试、构建或 diff。",
                "quarantined" =>
                    "Return 已整体隔离；只显示固定错误码，不展示不可信正文。",
                _ => "Return 状态已更新。",
            };
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplyHandoffs(IReadOnlyList<HandoffRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var previous   = SelectedHandoff;
        var selectedId = previous?.HandoffId;
        var approved = records
            .Where(item => string.Equals(item.Status, "approved", StringComparison.Ordinal))
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        ApprovedHandoffs = approved;

        if (selectedId is null)
        {
            SelectedHandoff = approved.FirstOrDefault();
            return;
        }

        var refreshed = approved.FirstOrDefault(item =>
            string.Equals(item.HandoffId, selectedId, StringComparison.Ordinal));
        if (refreshed is null)
        {
            _selectedHandoff = approved.FirstOrDefault();
            RaisePropertyChanged(nameof(SelectedHandoff));
            RaiseActionProperties();
            return;
        }

        if (previous is not null && HandoffEquivalent(previous, refreshed))
        {
            _selectedHandoff = previous;
            RaisePropertyChanged(nameof(SelectedHandoff));
            RaiseActionProperties();
            return;
        }
        SelectedHandoff = refreshed;
    }

    private void ApplyReturns(IReadOnlyList<ReturnRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var previous   = SelectedReturn;
        var selectedId = previous?.ReturnId;
        var ordered = records
            .OrderByDescending(item => item.UpdatedAt)
            .Take(100)
            .ToArray();
        RecentReturns = ordered;

        if (selectedId is null)
        {
            SelectedRecentReturn = ordered.FirstOrDefault();
            return;
        }

        var refreshed = ordered.FirstOrDefault(item =>
            string.Equals(item.ReturnId, selectedId, StringComparison.Ordinal));
        if (refreshed is null)
        {
            _selectedRecentReturn = ordered.FirstOrDefault();
            RaisePropertyChanged(nameof(SelectedRecentReturn));
            if (_selectedRecentReturn is not null)
            {
                SelectedReturn   = _selectedRecentReturn;
                IsPreviewVisible = true;
            }
            return;
        }

        if (previous is not null && ReturnEquivalent(previous, refreshed))
        {
            _selectedRecentReturn = refreshed;
            RaisePropertyChanged(nameof(SelectedRecentReturn));
            SelectedReturn   = previous;
            IsPreviewVisible = true;
            return;
        }
        SelectedRecentReturn = refreshed;
    }

    private void UpsertAndSelect(ReturnRecord record)
    {
        var records = RecentReturns
            .Where(item => !string.Equals(
                item.ReturnId,
                record.ReturnId,
                StringComparison.Ordinal))
            .Append(record)
            .OrderByDescending(item => item.UpdatedAt)
            .ToArray();
        RecentReturns        = records;
        SelectedRecentReturn = record;
        SelectedReturn       = record;
        IsPreviewVisible     = true;
    }

    private static bool HandoffEquivalent(HandoffRecord left, HandoffRecord right) =>
        string.Equals(left.HandoffId, right.HandoffId, StringComparison.Ordinal)
        && string.Equals(left.Status, right.Status, StringComparison.Ordinal)
        && string.Equals(left.RequestDigest, right.RequestDigest, StringComparison.Ordinal)
        && string.Equals(left.PackageDigest, right.PackageDigest, StringComparison.Ordinal);

    private static bool ReturnEquivalent(ReturnRecord left, ReturnRecord right) =>
        string.Equals(left.ReturnId, right.ReturnId, StringComparison.Ordinal)
        && string.Equals(left.Status, right.Status, StringComparison.Ordinal)
        && string.Equals(left.RequestDigest, right.RequestDigest, StringComparison.Ordinal)
        && string.Equals(left.PackageDigest, right.PackageDigest, StringComparison.Ordinal)
        && string.Equals(left.ManifestDigest, right.ManifestDigest, StringComparison.Ordinal)
        && string.Equals(left.QuarantineCode, right.QuarantineCode, StringComparison.Ordinal);

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanRunReturnSelfTest));
        RefreshCommand.NotifyCanExecuteChanged();
        RunSelfTestCommand.NotifyCanExecuteChanged();
    }

    private void HandleCommandError(Exception exception)
    {
        StatusMessage = FormatError(
            "操作失败；已有 Return 安全预览已保留。",
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

    private static HandoffRecord CreateSmokeHandoff() => new(
        "handoff-smoke-approved",
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "验证 Return 合同",
        "运行本地零变更 Return 合同验证。",
        "approved",
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase10a-handoff-preparation",
        "7a97694dfe4c1850def24d48b57ce8a8dbdee454",
        "internal",
        1,
        0,
        ["python-regression", "windows-wpf-behavior", "mac-core-arm64"],
        "20 turns · 1800 秒 · 1 并发 · 无网络工具",
        new string('a', 64),
        new string('b', 64),
        "approval-smoke",
        new DateTimeOffset(2026, 8, 5, 22, 0, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 1, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 30, 0, TimeSpan.Zero),
        ["Provider execution is disabled."]);

    private static ReturnRecord CreateSmokeReturn() => new(
        "return-smoke-validated",
        "handoff-smoke-approved",
        "contract_validated",
        "local-contract-self-test",
        new string('a', 64),
        new string('b', 64),
        new string('c', 64),
        ChangedFileCount: 0,
        EventCount: 3,
        [new ReturnValidationCheckRecord("return_contract", Passed: true)],
        [
            new ReturnEventSummaryRecord(1, "provider.session.started", "本地合同演练已开始。"),
            new ReturnEventSummaryRecord(2, "provider.progress", "正在验证固定 Return 合同。"),
            new ReturnEventSummaryRecord(3, "provider.returned", "零变更演练包已返回验证器。"),
        ],
        QuarantineCode: null,
        new DateTimeOffset(2026, 8, 5, 22, 2, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 2, 5, TimeSpan.Zero),
        "仅完成合同验证；未运行 Provider、代码、测试、构建、diff、worktree 或 Git 写操作。");
}
