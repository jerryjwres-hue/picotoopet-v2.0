using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

public sealed partial class ControlCenterSession
{
    /// <summary>读取 Mac Core 固定目标模板；设备令牌只在 Session 内从 Credential Manager 取用。</summary>
    public async Task<GoalTemplateRecord[]> GetGoalTemplatesAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.GetGoalTemplatesAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>读取最近的人类目标事实。</summary>
    public async Task<HumanGoalRecord[]> GetGoalsAsync(CancellationToken cancellationToken)
    {
        await using var client = CreateGoalCenterClient();
        return await client.GetGoalsAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>按 ID 读取一个人类目标。</summary>
    public async Task<HumanGoalRecord> GetGoalAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        await using var client = CreateGoalCenterClient();
        return await client.GetGoalAsync(goalId, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>只提交高层目标字段；Mac Core 继续拥有 Workflow、Task 与执行策略。</summary>
    public async Task<HumanGoalRecord> CreateGoalAsync(
        HumanGoalCreateRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateGoalCenterClient();
        return await client.CreateGoalAsync(request, idempotencyKey, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>读取已验证交接包元数据；Mac 本地路径不会进入 Windows。</summary>
    public async Task<GoalHandoffMetadataRecord> GetGoalHandoffAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        await using var client = CreateGoalCenterClient();
        return await client.GetGoalHandoffAsync(goalId, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>下载 Mac Core 已完成完整性验证的 Web GPT 交接 ZIP。</summary>
    public async Task<byte[]> DownloadGoalHandoffAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        await using var client = CreateGoalCenterClient();
        return await client.DownloadGoalHandoffAsync(goalId, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>读取交接包绑定的固定 Web GPT Prompt。</summary>
    public async Task<string> GetGoalHandoffPromptAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        await using var client = CreateGoalCenterClient();
        return await client.GetGoalHandoffPromptAsync(goalId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreClient CreateGoalCenterClient()
    {
        ThrowIfDisposed();
        if (_coordinator is null)
        {
            throw new InvalidOperationException("尚未连接 Mac Core。");
        }

        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("设备令牌不可用，请重新配对 Mac Core。");
        }

        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var baseUri)
            || baseUri.Scheme is not ("http" or "https"))
        {
            throw new InvalidOperationException("Mac Core 地址无效，请重新保存连接设置。");
        }

        return MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
