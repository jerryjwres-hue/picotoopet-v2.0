using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>2.3.20.1 Production 固定控制面；不暴露 workflow/model/endpoint/path/command 输入。</summary>
public sealed class ProductionPanelViewModel : ObservableObject, IDisposable
{
    public const string FixedProductionProfile = "production.comfyui.v1";
    public const string ProductionBoundaryText = "production_ready != publish-ready";

    private readonly ControlCenterSession? _session;
    private readonly ProductionExecutionService? _execution;
    private IReadOnlyList<ProductionEligibleCreativeRecord> _eligible = Array.Empty<ProductionEligibleCreativeRecord>();
    private IReadOnlyList<ProductionJobRecord> _jobs = Array.Empty<ProductionJobRecord>();
    private ProductionEligibleCreativeRecord? _selectedCreativePackage;
    private ProductionJobRecord? _selectedJob;
    private string _preflightStatus = "尚未执行本地 ComfyUI preflight。";
    private string _statusMessage = "Production 只消费 creative_ready/PASS Creative Package。";
    private bool _isBusy;
    private bool _disposed;

    public ProductionPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _execution = ProductionExecutionService.Create(session);
    }

    private ProductionPanelViewModel(
        IReadOnlyList<ProductionEligibleCreativeRecord> eligible,
        IReadOnlyList<ProductionJobRecord> jobs)
    {
        EligibleCreativePackages = eligible;
        Jobs = jobs;
        SelectedCreativePackage = eligible.Count > 0 ? eligible[0] : null;
        SelectedJob = jobs.Count > 0 ? jobs[0] : null;
        PreflightStatus = "ComfyUI loopback · smoke mode";
    }

    public IReadOnlyList<ProductionEligibleCreativeRecord> EligibleCreativePackages
    {
        get => _eligible;
        private set => SetProperty(ref _eligible, value);
    }

    public IReadOnlyList<ProductionJobRecord> Jobs
    {
        get => _jobs;
        private set => SetProperty(ref _jobs, value);
    }

    public ProductionEligibleCreativeRecord? SelectedCreativePackage
    {
        get => _selectedCreativePackage;
        set
        {
            if (SetProperty(ref _selectedCreativePackage, value))
            {
                RaiseActions();
            }
        }
    }

    public ProductionJobRecord? SelectedJob
    {
        get => _selectedJob;
        set
        {
            if (SetProperty(ref _selectedJob, value))
            {
                RaiseActions();
            }
        }
    }

    public string PreflightStatus
    {
        get => _preflightStatus;
        private set => SetProperty(ref _preflightStatus, value);
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
                RaiseActions();
            }
        }
    }

    public static string BoundaryText => ProductionBoundaryText;
    public static string ProfileText => FixedProductionProfile;
    public static string RendererText => "ComfyUI · http://127.0.0.1:8188 · Wan2.2 TI2V 5B";

    public bool CanCreate => !IsBusy && SelectedCreativePackage is not null;

    public bool CanPreflight => !IsBusy;

    public bool CanStart =>
        !IsBusy
        && SelectedJob is not null
        && SelectedJob.Status is "Planned" or "Claimed" or "Rendering";

    public bool CanCancel =>
        !IsBusy
        && SelectedJob is not null
        && SelectedJob.Status is "Ready" or "Planned" or "Claimed" or "Rendering" or "QualityCheck";

    public static ProductionPanelViewModel CreateForSmokeTest(
        IReadOnlyList<ProductionEligibleCreativeRecord>? eligible = null,
        IReadOnlyList<ProductionJobRecord>? jobs = null) =>
        new(
            eligible ?? Array.Empty<ProductionEligibleCreativeRecord>(),
            jobs ?? Array.Empty<ProductionJobRecord>());

    /// <summary>只刷新 Core 已验证的 eligible Creative Package 与 durable Production Job。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var selectedCreativeId = SelectedCreativePackage?.CreativePackageId;
            var selectedJobId = SelectedJob?.ProductionJobId;
            var eligibleTask = session.GetProductionEligibleAsync(cancellationToken);
            var jobsTask = session.GetProductionJobsAsync(cancellationToken);
            await Task.WhenAll(eligibleTask, jobsTask).ConfigureAwait(false);
            EligibleCreativePackages = await eligibleTask.ConfigureAwait(false);
            Jobs = await jobsTask.ConfigureAwait(false);
            SelectedCreativePackage = EligibleCreativePackages.FirstOrDefault(item =>
                item.CreativePackageId == selectedCreativeId)
                ?? (EligibleCreativePackages.Count > 0 ? EligibleCreativePackages[0] : null);
            SelectedJob = Jobs.FirstOrDefault(item => item.ProductionJobId == selectedJobId)
                ?? (Jobs.Count > 0 ? Jobs[0] : null);
            StatusMessage = $"可生产 Creative Package {EligibleCreativePackages.Count} 个；Production Job {Jobs.Count} 个。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>用固定 profile 和确定性幂等键创建 Production Job；没有 renderer 配置输入。</summary>
    public async Task CreateSelectedAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var selected = SelectedCreativePackage
            ?? throw new InvalidOperationException("请先选择一个 creative_ready Creative Package。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var created = await session.CreateProductionJobAsync(
                new ProductionJobCreateRequest(
                    selected.CreativePackageId,
                    FixedProductionProfile,
                    BuildIdempotencyKey(selected.CreativePackageId, selected.PackageDigest)),
                cancellationToken).ConfigureAwait(false);
            await RefreshAsync(cancellationToken).ConfigureAwait(false);
            SelectedJob = Jobs.FirstOrDefault(item => item.ProductionJobId == created.ProductionJobId)
                ?? created;
            StatusMessage = created.Status == "NeedsHuman"
                ? "Production Job 已创建，但含 20.1 不支持的 render_intent，已安全进入 NeedsHuman；不会调用 ComfyUI。"
                : "Production Job 与不可变 Plan 已创建，可先执行 Preflight 再启动本地渲染。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>只验证本机 loopback ComfyUI、workflow、模型哈希和数据根，不提交任何 prompt。</summary>
    public async Task PreflightAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var execution = RequireExecution();
        IsBusy = true;
        try
        {
            var result = await execution.PreflightAsync(cancellationToken).ConfigureAwait(false);
            PreflightStatus = result.IsReady
                ? $"PASS · {result.Detail} · {string.Join(" · ", result.Checks)}"
                : $"FAIL · {result.Detail}";
            StatusMessage = result.IsReady
                ? "Preflight 通过；Start 才会 claim Core Job 并提交固定 workflow。"
                : "Preflight 未通过；没有提交任何 ComfyUI render。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>启动所选 Planned Job；executor 只能运行 Core Plan 指定的 allowlisted workflow。</summary>
    public async Task StartSelectedAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var selected = SelectedJob ?? throw new InvalidOperationException("请先选择 Production Job。");
        if (!CanStart)
        {
            throw new InvalidOperationException("当前 Production Job 不可启动。 ");
        }
        var execution = RequireExecution();
        IsBusy = true;
        try
        {
            var package = await execution.RunAsync(selected.ProductionJobId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshAsync(cancellationToken).ConfigureAwait(false);
            SelectedJob = Jobs.FirstOrDefault(item => item.ProductionJobId == selected.ProductionJobId)
                ?? SelectedJob;
            StatusMessage = $"Production Package 已生成：{package.ProductionPackageId} · SHA {package.PackageDigest[..12]}…；仍未发布。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>取消 Core 中活动 Job；不删除 Creative Package、模型或已提交的内容寻址输出。</summary>
    public async Task CancelSelectedAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var selected = SelectedJob ?? throw new InvalidOperationException("请先选择 Production Job。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            _ = await session.CancelProductionJobAsync(selected.ProductionJobId, cancellationToken)
                .ConfigureAwait(false);
            await RefreshAsync(cancellationToken).ConfigureAwait(false);
            StatusMessage = "Production Job 已请求取消；不会删除 Creative Package 或已验证模型。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void RaiseActions()
    {
        RaisePropertyChanged(nameof(CanCreate));
        RaisePropertyChanged(nameof(CanPreflight));
        RaisePropertyChanged(nameof(CanStart));
        RaisePropertyChanged(nameof(CanCancel));
    }

    private static string BuildIdempotencyKey(string creativePackageId, string packageDigest)
    {
        var canonical = $"{FixedProductionProfile}\n{creativePackageId}\n{packageDigest}";
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)))
            .ToLowerInvariant();
        return $"windows-production-{digest}";
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问 Mac Core。");

    private ProductionExecutionService RequireExecution() =>
        _execution ?? throw new InvalidOperationException("Smoke test 模式不能访问 ComfyUI。");

    private void ThrowIfDisposed()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        if (_execution is not null)
        {
            _execution.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
    }
}
