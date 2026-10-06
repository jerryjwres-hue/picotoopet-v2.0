using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>仅保存 Mac Core continuation 投影；不会保存原始 Web GPT 返回。</summary>
public sealed class GoalVideoContinuationViewModel : ObservableObject
{
    private readonly IGoalVideoContinuationGateway? _gateway;
    private string? _goalId;
    private bool _available;
    private bool _isBusy;
    private string _errorMessage = string.Empty;
    private GoalVideoContinuationRecord? _continuation;

    public GoalVideoContinuationViewModel(IGoalVideoContinuationGateway? gateway) =>
        _gateway = gateway;

    public GoalVideoContinuationRecord? Continuation
    {
        get => _continuation;
        private set
        {
            if (SetProperty(ref _continuation, value))
            {
                RaisePropertyChanged(nameof(StatusText));
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
            return $"Creative：{Continuation.CreativeStatus} · Production：{Continuation.ProductionStatus ?? "尚未创建"}";
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
        RaisePropertyChanged(nameof(CanSubmit));
        RaisePropertyChanged(nameof(StatusText));
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_gateway is null || _goalId is null)
        {
            Continuation = null;
            ErrorMessage = string.Empty;
            return;
        }
        try
        {
            Continuation = await _gateway.GetGoalVideoContinuationAsync(_goalId, cancellationToken)
                .ConfigureAwait(false);
            ErrorMessage = string.Empty;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ApiException exception) when (exception.StatusCode == 404)
        {
            Continuation = null;
            ErrorMessage = string.Empty;
        }
        catch (Exception exception)
        {
            ErrorMessage = ToSafeError(exception);
        }
    }

    public async Task SubmitAsync(
        JsonElement payload,
        CancellationToken cancellationToken = default)
    {
        if (_gateway is null || _goalId is null || !CanSubmit)
        {
            return;
        }
        IsBusy = true;
        ErrorMessage = string.Empty;
        try
        {
            Continuation = await _gateway.SubmitGoalVideoReturnAsync(
                _goalId,
                payload,
                cancellationToken).ConfigureAwait(false);
            await RefreshAfterAcceptedPostAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ApiException exception) when (exception.Retryable)
        {
            await ReconcileAmbiguousPostAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (ApiException exception) when (exception.StatusCode == 409)
        {
            ErrorMessage = ToSafeError(exception);
        }
        catch (Exception exception)
        {
            ErrorMessage = ToSafeError(exception);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshAfterAcceptedPostAsync(CancellationToken cancellationToken)
    {
        try
        {
            Continuation = await _gateway!.GetGoalVideoContinuationAsync(_goalId!, cancellationToken)
                .ConfigureAwait(false);
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

    private async Task ReconcileAmbiguousPostAsync(CancellationToken cancellationToken)
    {
        try
        {
            Continuation = await _gateway!.GetGoalVideoContinuationAsync(_goalId!, cancellationToken)
                .ConfigureAwait(false);
            ErrorMessage = string.Empty;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            ErrorMessage = "提交结果暂时无法确认；请保留同一返回内容后重试。";
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
