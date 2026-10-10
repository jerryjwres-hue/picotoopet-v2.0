using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>仅保存 Mac Core continuation 投影；不会保存原始 Web GPT 返回。</summary>
public sealed class GoalVideoContinuationViewModel : ObservableObject
{
    private readonly IGoalVideoContinuationGateway? _gateway;
    private readonly IGoalProductionAutopilotObserver? _autopilot;
    private readonly IPostProductionDeliveryObserver? _finalVideo;
    // Source-compatibility for the frozen C004 coordinator smoke harness only.
    // The production composition root never injects this observer.
    private readonly IGoalFinalVideoObserver? _legacyFinalVideo;
    private string? _goalId;
    private bool _available;
    private bool _isBusy;
    private string _errorMessage = string.Empty;
    private GoalVideoContinuationRecord? _continuation;
    private string? _localProductionStatus;
    private string? _localFinalVideoStatus;
    private bool _canOpenFinalVideo;
    private int _openingFinalVideo;

    public GoalVideoContinuationViewModel(
        IGoalVideoContinuationGateway? gateway,
        IGoalProductionAutopilotObserver? autopilot = null,
        IPostProductionDeliveryObserver? finalVideo = null)
    {
        _gateway = gateway;
        _autopilot = autopilot;
        _finalVideo = finalVideo;
    }

    /// <summary>Compatibility only: existing C004 smoke tests still bind their original observer.</summary>
    public GoalVideoContinuationViewModel(
        IGoalVideoContinuationGateway? gateway,
        IGoalProductionAutopilotObserver? autopilot,
        IGoalFinalVideoObserver legacyFinalVideo)
    {
        _gateway = gateway;
        _autopilot = autopilot;
        _legacyFinalVideo = legacyFinalVideo ?? throw new ArgumentNullException(nameof(legacyFinalVideo));
    }

    public GoalVideoContinuationRecord? Continuation
    {
        get => _continuation;
        private set
        {
            var previousJobId = _continuation?.ProductionJobId;
            if (SetProperty(ref _continuation, value))
            {
                if (!string.Equals(previousJobId, value?.ProductionJobId, StringComparison.Ordinal))
                {
                    _localProductionStatus = null;
                    _localFinalVideoStatus = null;
                    _canOpenFinalVideo = false;
                }
                RaisePropertyChanged(nameof(StatusText));
                RaisePropertyChanged(nameof(ProductionStatusText));
                RaisePropertyChanged(nameof(CanOpenFinalVideo));
            }
        }
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanSubmit));
                RaisePropertyChanged(nameof(StatusText));
            }
        }
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (SetProperty(ref _errorMessage, value))
            {
                RaisePropertyChanged(nameof(StatusText));
            }
        }
    }

    public bool CanSubmit => _gateway is not null && _available && !IsBusy;

    public bool CanOpenFinalVideo => _canOpenFinalVideo && Volatile.Read(ref _openingFinalVideo) == 0;

    public string StatusText
    {
        get
        {
            if (IsBusy)
            {
                return "正在向 Mac Core 提交 Web GPT 返回…";
            }
            if (!string.IsNullOrWhiteSpace(ErrorMessage))
            {
                return ErrorMessage;
            }
            if (Continuation is null)
            {
                return "尚未提交 Web GPT 返回";
            }
            return $"Creative：{Continuation.CreativeStatus} · Production：{ProductionStatusText}";
        }
    }

    public string ProductionStatusText
    {
        get
        {
            var coreStatus = Continuation?.ProductionStatus;
            if (string.Equals(coreStatus, "production_ready", StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(_localFinalVideoStatus))
            {
                return _localFinalVideoStatus;
            }
            if (string.Equals(coreStatus, "Ready", StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(_localProductionStatus))
            {
                return _localProductionStatus;
            }
            return coreStatus switch
            {
                null => "尚未创建",
                "Ready" => "等待本地生产启动",
                "Claimed" => "已认领，准备渲染",
                "Preflight" => "正在检查本地生产环境",
                "Rendering" => "正在本地渲染",
                "Collecting" => "正在收集渲染结果",
                "QualityCheck" => "正在进行质量检查",
                "production_ready" => "生产成品已就绪",
                "NeedsHuman" => "需要人工处理",
                "Failed" => "生产失败",
                "Cancelled" => "生产已取消",
                _ => "生产状态暂不可识别",
            };
        }
    }

    public void SetContext(HumanGoalRecord? goal, GoalHandoffMetadataRecord? handoff)
    {
        var nextGoalId = goal is { Status: "Completed" }
            && goal.IntentType is "video.creative" or "product.research_to_video"
            && handoff is { HandoffReady: true }
            && string.Equals(goal.GoalId, handoff.GoalId, StringComparison.Ordinal)
                ? goal.GoalId
                : null;
        if (!string.Equals(_goalId, nextGoalId, StringComparison.Ordinal))
        {
            _goalId = nextGoalId;
            Continuation = null;
            ErrorMessage = string.Empty;
        }
        _available = nextGoalId is not null;
        ObserveAutopilot();
        RaisePropertyChanged(nameof(CanSubmit));
        RaisePropertyChanged(nameof(StatusText));
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        var goalId = _goalId;
        if (_gateway is null || goalId is null)
        {
            Continuation = null;
            ErrorMessage = string.Empty;
            return;
        }
        try
        {
            var continuation = await _gateway.GetGoalVideoContinuationAsync(goalId, cancellationToken)
                .ConfigureAwait(false);
            if (!IsCurrentGoal(goalId))
            {
                return;
            }
            Continuation = continuation;
            ErrorMessage = string.Empty;
            ObserveAutopilot();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ApiException exception) when (exception.StatusCode == 404)
        {
            if (!IsCurrentGoal(goalId))
            {
                return;
            }
            Continuation = null;
            ErrorMessage = string.Empty;
            ObserveAutopilot();
        }
        catch (Exception exception)
        {
            if (IsCurrentGoal(goalId))
            {
                ErrorMessage = ToSafeError(exception);
            }
        }
    }

    public async Task SubmitAsync(
        JsonElement payload,
        CancellationToken cancellationToken = default)
    {
        var goalId = _goalId;
        if (_gateway is null || goalId is null || !CanSubmit)
        {
            return;
        }
        IsBusy = true;
        ErrorMessage = string.Empty;
        try
        {
            var continuation = await _gateway.SubmitGoalVideoReturnAsync(
                goalId,
                payload,
                cancellationToken).ConfigureAwait(false);
            if (!IsCurrentGoal(goalId))
            {
                return;
            }
            Continuation = continuation;
            ObserveAutopilot();
            await RefreshAfterAcceptedPostAsync(goalId, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ApiException exception) when (exception.Retryable)
        {
            if (IsCurrentGoal(goalId))
            {
                await ReconcileAmbiguousPostAsync(goalId, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (ApiException exception) when (exception.StatusCode == 409)
        {
            if (IsCurrentGoal(goalId))
            {
                ErrorMessage = ToSafeError(exception);
            }
        }
        catch (Exception exception)
        {
            if (IsCurrentGoal(goalId))
            {
                ErrorMessage = ToSafeError(exception);
            }
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshAfterAcceptedPostAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        try
        {
            var continuation = await _gateway!.GetGoalVideoContinuationAsync(goalId, cancellationToken)
                .ConfigureAwait(false);
            if (IsCurrentGoal(goalId))
            {
                Continuation = continuation;
                ObserveAutopilot();
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            // POST 已返回 Core 投影；GET 暂不可用时保留该服务端事实，定时刷新会继续对账。
        }
    }

    private async Task ReconcileAmbiguousPostAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        try
        {
            var continuation = await _gateway!.GetGoalVideoContinuationAsync(goalId, cancellationToken)
                .ConfigureAwait(false);
            if (!IsCurrentGoal(goalId))
            {
                return;
            }
            Continuation = continuation;
            ErrorMessage = string.Empty;
            ObserveAutopilot();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            if (IsCurrentGoal(goalId))
            {
                ErrorMessage = "提交结果暂时无法确认；请保留同一返回内容后重试。";
            }
        }
    }

    private bool IsCurrentGoal(string goalId) =>
        string.Equals(_goalId, goalId, StringComparison.Ordinal);

    private void ObserveAutopilot()
    {
        if (_autopilot is not null)
        {
            var productionSnapshot = _autopilot.Observe(_goalId, Continuation);
            _localProductionStatus = productionSnapshot.StatusText;
        }
        if (_finalVideo is not null)
        {
            var finalSnapshot = _finalVideo.Observe(_goalId, Continuation);
            _localFinalVideoStatus = finalSnapshot.StatusText;
            _canOpenFinalVideo = finalSnapshot.CanOpen;
        }
        else if (_legacyFinalVideo is not null)
        {
            var legacySnapshot = _legacyFinalVideo.Observe(_goalId, Continuation);
            _localFinalVideoStatus = legacySnapshot.StatusText;
            _canOpenFinalVideo = legacySnapshot.CanOpen;
        }
        else
        {
            _localFinalVideoStatus = null;
            _canOpenFinalVideo = false;
        }
        RaisePropertyChanged(nameof(ProductionStatusText));
        RaisePropertyChanged(nameof(StatusText));
        RaisePropertyChanged(nameof(CanOpenFinalVideo));
    }

    /// <summary>Legacy C004 smoke compatibility, never used by the one production UI action.</summary>
    [Obsolete("Use OpenFinalVideoAsync with IPostProductionDeliveryObserver for Goal Center.")]
    public bool OpenFinalVideo()
    {
        if (_legacyFinalVideo is null || !CanOpenFinalVideo)
        {
            return false;
        }
        var opened = _legacyFinalVideo.OpenCurrent();
        if (!opened)
        {
            _localFinalVideoStatus = "最终视频暂时无法打开；请稍后重试。";
            _canOpenFinalVideo = false;
            RaisePropertyChanged(nameof(ProductionStatusText));
            RaisePropertyChanged(nameof(StatusText));
            RaisePropertyChanged(nameof(CanOpenFinalVideo));
        }
        return opened;
    }

    public async Task<bool> OpenFinalVideoAsync(CancellationToken cancellationToken = default)
    {
        if (_finalVideo is null || !_canOpenFinalVideo
            || Interlocked.CompareExchange(ref _openingFinalVideo, 1, 0) != 0)
        {
            return false;
        }
        var goalAtClick = _goalId;
        var jobAtClick = Continuation?.ProductionJobId;
        RaisePropertyChanged(nameof(CanOpenFinalVideo));
        try
        {
            // The coordinator revalidates exact managed bytes/manifest off the UI thread.
            // Do not allow a previous Goal/job's completion to mutate the new Goal display.
            var opened = await _finalVideo.OpenCurrentAsync(cancellationToken).ConfigureAwait(true);
            if (!opened && string.Equals(_goalId, goalAtClick, StringComparison.Ordinal)
                && string.Equals(Continuation?.ProductionJobId, jobAtClick, StringComparison.Ordinal))
            {
                _localFinalVideoStatus = "最终视频暂时无法打开；请稍后重试。";
                _canOpenFinalVideo = false;
                RaisePropertyChanged(nameof(ProductionStatusText));
                RaisePropertyChanged(nameof(StatusText));
            }
            return opened;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
        catch (Exception)
        {
            if (string.Equals(_goalId, goalAtClick, StringComparison.Ordinal)
                && string.Equals(Continuation?.ProductionJobId, jobAtClick, StringComparison.Ordinal))
            {
                _localFinalVideoStatus = "最终视频暂时无法打开；请稍后重试。";
                _canOpenFinalVideo = false;
                RaisePropertyChanged(nameof(ProductionStatusText));
                RaisePropertyChanged(nameof(StatusText));
            }
            return false;
        }
        finally
        {
            Interlocked.Exchange(ref _openingFinalVideo, 0);
            RaisePropertyChanged(nameof(CanOpenFinalVideo));
        }
    }

    private static string ToSafeError(Exception exception) => exception switch
    {
        ApiException api when api.StatusCode is 401 or 403 => "目标中心认证失败，请重新连接 Mac Core。",
        ApiException api when api.StatusCode == 409 => "返回被 Core 拒绝或与已采纳返回冲突；现有结果未被修改。",
        ApiException api when api.Retryable => "目标中心暂时不可用；请保留同一返回内容后重试。",
        GoalVideoReturnParseException => "剪贴板内容不是有效的有界 GPT 返回 JSON。",
        _ => "Web GPT 返回暂时无法提交；现有目标与生产事实未被修改。",
    };
}
