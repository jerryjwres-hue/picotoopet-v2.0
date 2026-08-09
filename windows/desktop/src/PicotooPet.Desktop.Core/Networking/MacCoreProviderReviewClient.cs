using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>访问固定 Review/Adoption/Commit/Publication REST 合同；不接受 patch、路径或任意正文。</summary>
public sealed class MacCoreProviderReviewClient : IAsyncDisposable
{
    private const int MaxResponseBytes = 192 * 1024;
    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private MacCoreProviderReviewClient(HttpClient client, Uri baseUri, string token, bool ownsClient)
    {
        _httpClient = client;
        _baseUri = baseUri.AbsoluteUri.EndsWith('/') ? baseUri : new Uri(baseUri.AbsoluteUri + "/");
        _token = string.IsNullOrWhiteSpace(token)
            ? throw new ArgumentException("设备令牌不能为空。", nameof(token))
            : token;
        _ownsClient = ownsClient;
    }

    /// <summary>创建有界超时的长期 Review 客户端。</summary>
    public static MacCoreProviderReviewClient Create(Uri baseUri, string token)
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            ConnectTimeout = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer = 4,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
        return new MacCoreProviderReviewClient(client, baseUri, token, ownsClient: true);
    }

    public Task<ProviderReviewRecord> GetReviewAsync(
        string sessionId,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderReviewRecord>(
            HttpMethod.Get,
            $"api/v1/provider-sessions/{Uri.EscapeDataString(sessionId)}/review",
            null,
            cancellationToken);

    public Task<ProviderReviewRecord> AcceptAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderReviewRecord>(
            HttpMethod.Post,
            $"api/v1/provider-sessions/{Uri.EscapeDataString(sessionId)}/review/accept",
            idempotencyKey,
            cancellationToken);

    public Task<ProviderReviewRecord> RejectAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderReviewRecord>(
            HttpMethod.Post,
            $"api/v1/provider-sessions/{Uri.EscapeDataString(sessionId)}/review/reject",
            idempotencyKey,
            cancellationToken);

    public Task<ProviderAdoptionCandidateRecord[]> GetCandidatesAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderAdoptionCandidateRecord[]>(
            HttpMethod.Get,
            "api/v1/provider-adoption-candidates?limit=100",
            null,
            cancellationToken);

    /// <summary>空 body 准备一个新的 digest-bound 本地提交审批。</summary>
    public Task<ProviderCommitCandidateRecord> PrepareCommitAsync(
        string adoptionCandidateId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderCommitCandidateRecord>(
            HttpMethod.Post,
            $"api/v1/provider-adoption-candidates/{Uri.EscapeDataString(adoptionCandidateId)}/commit/prepare",
            idempotencyKey,
            cancellationToken);

    public Task<ProviderCommitCandidateRecord[]> GetCommitCandidatesAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderCommitCandidateRecord[]>(
            HttpMethod.Get,
            "api/v1/provider-commit-candidates?limit=100",
            null,
            cancellationToken);

    /// <summary>空 body 准备 exact Push + Draft PR 组合审批。</summary>
    public Task<ProviderPublicationCandidateRecord> PreparePublicationAsync(
        string commitCandidateId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderPublicationCandidateRecord>(
            HttpMethod.Post,
            $"api/v1/provider-commit-candidates/{Uri.EscapeDataString(commitCandidateId)}/publication/prepare",
            idempotencyKey,
            cancellationToken);

    public Task<ProviderPublicationCandidateRecord[]> GetPublicationCandidatesAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderPublicationCandidateRecord[]>(
            HttpMethod.Get,
            "api/v1/provider-publication-candidates?limit=100",
            null,
            cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUri,
        string? idempotencyKey,
        CancellationToken cancellationToken)
    {
        var traceId = Guid.NewGuid().ToString("N");
        using var request = new HttpRequestMessage(method, new Uri(_baseUri, relativeUri));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);
        if (!string.IsNullOrWhiteSpace(idempotencyKey))
        {
            request.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
        }
        try
        {
            using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
            var data = await ReadBoundedAsync(response.Content, MaxResponseBytes, cancellationToken)
                .ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                string message;
                try
                {
                    using var document = JsonDocument.Parse(data);
                    var error = document.RootElement.GetProperty("error");
                    var code = error.GetProperty("code").GetString() ?? "HTTP_ERROR";
                    message = error.GetProperty("message").GetString() ?? "Provider Review 请求失败。";
                    throw new ApiException(
                        code,
                        message,
                        retryable: (int)response.StatusCode >= 500,
                        traceId,
                        (int)response.StatusCode);
                }
                catch (JsonException)
                {
                    throw new ApiException(
                        "HTTP_ERROR",
                        $"Provider Review 返回 HTTP {(int)response.StatusCode}。",
                        retryable: (int)response.StatusCode >= 500,
                        traceId,
                        (int)response.StatusCode);
                }
            }
            return JsonSerializer.Deserialize<T>(data, JsonOptions)
                ?? throw new ApiException(
                    "EMPTY_RESPONSE",
                    "Mac Core 返回了空 Review 响应。",
                    retryable: true,
                    traceId,
                    (int)response.StatusCode);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (OperationCanceledException exception)
        {
            throw new ApiException(
                "NETWORK_TIMEOUT",
                "读取 Review 状态超时。",
                retryable: true,
                traceId,
                0,
                exception);
        }
        catch (HttpRequestException exception)
        {
            throw new ApiException(
                "NETWORK_ERROR",
                "无法连接 Mac Core Review 接口。",
                retryable: true,
                traceId,
                exception.StatusCode is null ? 0 : (int)exception.StatusCode.Value,
                exception);
        }
    }

    private static async Task<byte[]> ReadBoundedAsync(
        HttpContent content,
        int maxBytes,
        CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is long length && length > maxBytes)
        {
            throw new ApiException("RESPONSE_TOO_LARGE", "Review 响应超过安全上限。", false, "local", 0);
        }
        await using var stream = await content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var buffer = new MemoryStream(capacity: Math.Min(maxBytes, 16 * 1024));
        var block = new byte[8192];
        var total = 0;
        while (true)
        {
            var read = await stream.ReadAsync(block.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                return buffer.ToArray();
            }
            total = checked(total + read);
            if (total > maxBytes)
            {
                throw new ApiException("RESPONSE_TOO_LARGE", "Review 响应超过安全上限。", false, "local", 0);
            }
            await buffer.WriteAsync(block.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
        }
    }

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _httpClient.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}