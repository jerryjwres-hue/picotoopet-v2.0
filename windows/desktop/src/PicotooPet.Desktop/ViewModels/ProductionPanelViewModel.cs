using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.QualityObservation;
using System.IO;
using System.Windows.Media.Imaging;

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
    private IVisualObservation? _visualObservation;
    private CancellationTokenSource? _visualCancellation;
    private readonly SynchronizationContext? _visualContext = SynchronizationContext.Current;
    private int _visualRevision;
    private bool _isObservingVisuals;
    private string _visualVerdict = "UNVERIFIED";
    private string _visualDetail = "尚未生成视觉证据；机器观察不代表人工 ACCEPT 或 C011。";
    private BitmapSource? _visualContactSheet;
    private bool _useOptionalVisualVlm;

    public ProductionPanelViewModel(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _execution = ProductionExecutionService.Create(session);
        AttachVisualObservation(VisualReviewObservation.Create(session));
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
                InvalidateVisualObservation();
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
        get => _isBusy || _isObservingVisuals;
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
        && SelectedJob.Status is "Ready" or "Planned" or "Claimed" or "Rendering";

    public bool CanCancel =>
        !IsBusy
        && SelectedJob is not null
        && SelectedJob.Status is "Ready" or "Planned" or "Claimed" or "Rendering" or "QualityCheck";

    public string VisualReviewVerdict { get => _visualVerdict; private set => SetProperty(ref _visualVerdict, value); }
    public string VisualReviewDetail { get => _visualDetail; private set => SetProperty(ref _visualDetail, value); }
    public BitmapSource? VisualReviewContactSheet { get => _visualContactSheet; private set => SetProperty(ref _visualContactSheet, value); }
    public bool UseOptionalVisualVlm { get => _useOptionalVisualVlm; set => SetProperty(ref _useOptionalVisualVlm, value); }
    public bool IsObservingVisuals => _isObservingVisuals;
    public bool CanObserveSelectedVisuals => !_disposed && !IsBusy && !_isObservingVisuals && _visualObservation is not null
        && SelectedJob is { Status: "production_ready" } job && VisualReviewObservation.IsSha(job.PlanDigest);
    public bool CanUseVisualReviewButton => _isObservingVisuals || CanObserveSelectedVisuals;
    public string VisualReviewButtonText => _isObservingVisuals ? "取消只读视觉观察" : "生成视觉证据（CPU，只读）";

    public static ProductionPanelViewModel CreateForVisualObservationSmokeTest(IReadOnlyList<ProductionJobRecord> jobs, IVisualObservation observer)
    {
        var model = new ProductionPanelViewModel(Array.Empty<ProductionEligibleCreativeRecord>(), jobs);
        model.AttachVisualObservation(observer); return model;
    }
    private void AttachVisualObservation(IVisualObservation observer)
    { _visualObservation = observer; observer.Invalidated += VisualSessionChanged; }
    private void VisualSessionChanged(object? sender, EventArgs e) => InvalidateVisualObservation();
    private void InvalidateVisualObservation()
    {
        Interlocked.Increment(ref _visualRevision);
        try { _visualCancellation?.Cancel(); } catch (ObjectDisposedException) { }
        void Clear()
        {
            if (_disposed) return;
            VisualReviewVerdict = "UNVERIFIED"; VisualReviewContactSheet = null;
            VisualReviewDetail = "选中项或会话已变化；旧视觉结果已作废，需重新点击核对来源。";
        }
        if (_visualContext is not null && SynchronizationContext.Current != _visualContext) _visualContext.Post(_ => Clear(), null);
        else Clear();
    }
    public void CancelVisualObservation()
    { _visualCancellation?.Cancel(); }

    public async Task ObserveSelectedVisualsAsync(Func<VisualReadRequest, CancellationToken, Task<VisualReadConsent>> consent,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        if (!CanObserveSelectedVisuals || SelectedJob is not { } selected || _visualObservation is null) return;
        var revision = Volatile.Read(ref _visualRevision);
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        cancellation.CancelAfter(TimeSpan.FromMinutes(5)); _visualCancellation = cancellation;
        _isObservingVisuals = true; IsBusy = true;
        VisualReviewVerdict = "UNVERIFIED"; VisualReviewContactSheet = null;
        VisualReviewDetail = "只读取选中 Job 的冻结计划和产物身份；核对三镜头后才请求文件读取同意。";
        RaiseActions();
        try
        {
            var result = await _visualObservation.ObserveAsync(selected, UseOptionalVisualVlm, consent, cancellation.Token).ConfigureAwait(true);
            if (_disposed || revision != Volatile.Read(ref _visualRevision) || SelectedJob?.ProductionJobId != selected.ProductionJobId) return;
            if (cancellation.IsCancellationRequested) result = VisualReviewObservation.Unverified("观察已取消或超时；不会改变生产状态。");
            if (result.Verdict is not (VisualObservationVerdict.Review or VisualObservationVerdict.RejectSuspect or VisualObservationVerdict.Unverified))
                result = VisualReviewObservation.Unverified("不支持的机器结论；没有人工 ACCEPT。");
            if (result.ContactSheetPng is { Length: > 0 } png)
            {
                using var stream = new MemoryStream(png);
                var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
                image.StreamSource = stream; image.EndInit(); image.Freeze(); VisualReviewContactSheet = image;
            }
            VisualReviewVerdict = result.Verdict switch { VisualObservationVerdict.Review => "REVIEW", VisualObservationVerdict.RejectSuspect => "REJECT_SUSPECT", _ => "UNVERIFIED" }; VisualReviewDetail = result.Detail;
        }
        catch (Exception)
        {
            if (!_disposed && revision == Volatile.Read(ref _visualRevision))
            { VisualReviewVerdict = "UNVERIFIED"; VisualReviewContactSheet = null; VisualReviewDetail = "只读观察未完成；未改变生产状态或生成任何 ACCEPT。"; }
        }
        finally
        {
            _visualCancellation = null; _isObservingVisuals = false; IsBusy = false;
            RaisePropertyChanged(nameof(IsBusy)); RaiseActions();
        }
    }

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

    /// <summary>启动所选 Ready/可恢复 Job；executor 只能运行 Core Plan 指定的 allowlisted workflow。</summary>
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
        RaisePropertyChanged(nameof(CanObserveSelectedVisuals));
        RaisePropertyChanged(nameof(CanUseVisualReviewButton));
        RaisePropertyChanged(nameof(IsObservingVisuals));
        RaisePropertyChanged(nameof(VisualReviewButtonText));
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
        Interlocked.Increment(ref _visualRevision); _visualCancellation?.Cancel();
        if (_visualObservation is not null) { _visualObservation.Invalidated -= VisualSessionChanged; _visualObservation.Dispose(); }
        if (_execution is not null)
        {
            _execution.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
    }
}
