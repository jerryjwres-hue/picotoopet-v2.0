using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>全部调用复用原配对凭据；不创建或读取 OwnerPrincipal 凭据。</summary>
public sealed partial class ControlCenterSession
{
    private async Task<T> WithScopedStudioClientAsync<T>(Func<MacCoreClient, Task<T>> operation)
    {
        ThrowIfDisposed();
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }

        // 设备认证仅由既有 Credential Manager 提供，不显示或持久化在新 UI。
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        ValidateConnectionInput(baseUrl, token, out var baseUri);
        await using var client = MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
        return await operation(client).ConfigureAwait(false);
    }

    public Task<JsonElement> GetScopedOwnerPacketsAsync(
        string projectId, string characterRef, string subjectKey, string characterSha,
        CancellationToken cancellationToken) =>
        WithScopedStudioClientAsync(client => client.GetScopedOwnerPacketsAsync(
            projectId, characterRef, subjectKey, characterSha, cancellationToken));

    public Task<string> PreviewOwnerPacketAsync(JsonElement packet, CancellationToken cancellationToken) =>
        WithScopedStudioClientAsync(client => client.PreviewOwnerPacketAsync(packet, cancellationToken));

    public async Task CommitReviewedOwnerPacketAsync(
        JsonElement packet, string digest, CancellationToken cancellationToken)
    {
        await WithScopedStudioClientAsync(async client =>
        {
            await client.CommitReviewedOwnerPacketAsync(packet, digest, cancellationToken).ConfigureAwait(false);
            return true;
        }).ConfigureAwait(false);
    }

    public Task<string> SubmitScopedStoryGoalAsync(
        JsonElement storyPack, string projectId, string characterRef, string characterSha,
        string subjectKey, string packetDigest, string subjectDigest, string storyPackDigest,
        string motionDigest, CancellationToken cancellationToken) =>
        WithScopedStudioClientAsync(client => client.SubmitScopedStoryGoalAsync(
            storyPack, projectId, characterRef, characterSha, subjectKey, packetDigest,
            subjectDigest, storyPackDigest, motionDigest, cancellationToken));
}
