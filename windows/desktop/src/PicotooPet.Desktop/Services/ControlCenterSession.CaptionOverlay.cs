using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>C008B：复用当前已配对 Core 凭据读取 C008A2 计划；不持久化任何渲染配置，也不记录文案。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<CaptionOverlayPlanResponseRecord> GetCaptionOverlayPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core，无法读取文字叠加计划。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }
        await using var client = MacCoreCaptionOverlayClient.Create(
            MacCoreClientOptions.CreateDefault(baseUri, token));
        return await client.GetCaptionOverlayPlanAsync(productionJobId, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>读取已认证计划并应用到已验证的 C004 产物；返回派生视觉产物（或空计划直通）。</summary>
    public async Task<TextOverlayArtifact> ApplyCaptionOverlaysAsync(
        FinalVideoArtifact finalVideo,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(finalVideo);
        var plan = await GetCaptionOverlayPlanAsync(finalVideo.ProductionJobId, cancellationToken)
            .ConfigureAwait(false);
        return await WindowsCaptionOverlayService.Create()
            .ApplyAsync(finalVideo, plan, cancellationToken)
            .ConfigureAwait(false);
    }
}
