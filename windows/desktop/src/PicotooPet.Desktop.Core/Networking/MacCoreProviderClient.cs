using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Windows 只访问 Provider 状态、额度确认、会话读取与紧急取消；Session 创建权归 Mac Core。</summary>
public sealed class MacCoreProviderClient : IAsyncDisposable
{
    private const int MaxProviderResponseBytes = 128 * 1024;
    private const int MaxApiErrorBytes         = 64 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;

    public MacCoreProviderClient(HttpClient httpClient, Uri baseUri, string token)
        : this(httpClient, baseUri, token, ownsClient: false)
    {
    }

    private MacCoreProviderClient(
        HttpClient httpClient,
        Uri baseUri,
        string token,
        bool ownsClient)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _baseUri = EnsureTrailingSlash(baseUri ?? throw new ArgumentNullException(nameof(baseUri)));
        _token = string.IsNullOrWhiteSpace(token)
            ? throw new ArgumentException("设备令牌不能为空。", nameof(token))
            : token;
        _ownsClient = ownsClient;
    }

    /// <summary>创建具有固定连接池与超时的长期 Provider 客户端。</summary>
    public static MacCoreProviderClient Create(Uri baseUri, string token)
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime    = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout              = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer     = 4,
            AutomaticDecompression      = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
        return new MacCoreProviderClient(client, baseUri, token, ownsClient: true);
    }

    public Task<ProviderStatusRecord> GetStatusAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderStatusRecord>(
            HttpMethod.Get,
            "api/v1/providers/codex/status",
            payload: null,
            idempotencyKey: null,
            cancellationToken);

    public Task<ProviderSessionRecord[]> GetSessionsAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ProviderSessionRecord[]>(
            HttpMethod.Get,
            "api/v1/provider-sessions?limit=100",
            payload: null,
            idempotencyKey: null,
            cancellationToken);

    public Task<ProviderSessionRecord> GetSessionAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        return SendAsync<ProviderSessionRecord>(
            HttpMethod.Get,
            $"api/v1/provider-sessions/{Uri.EscapeDataString(sessionId)}",
            payload: null,
            idempotencyKey: null,
            cancellationToken);
    }

    public Task<ProviderUsageConfirmationRecord> ConfirmUsageAsync(
        string handoffId,
        string usageStatus,
        string idempotencyKey,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        ArgumentException.ThrowIfNullOrWhiteSpace(usageStatus);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        return SendAsync<ProviderUsageConfirmationRecord>(
            HttpMethod.Post,
            $"api/v1/handoffs/{Uri.EscapeDataString(handoffId)}/provider-usage-confirmation",
            new ProviderUsageConfirmationRequest(usageStatus),
            idempotencyKey,
            cancellationToken);
    }

    public Task<ProviderSessionRecord> CancelSessionAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        return SendAsync<ProviderSessionRecord>(
            HttpMethod.Post,
            $"api/v1/provider-sessions/{Uri.EscapeDataString(sessionId)}/cancel",
            payload: null,
            idempotencyKey,
            cancellationToken);
    }

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUri,
        object? payload,
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
        if (payload is not null)
        {
            request.Content = JsonContent.Create(payload, options: JsonOptions);
        }

        try
        {
            using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
            var responseTrace = response.Headers.TryGetValues(
                    "X-Picotoo-Trace-Id",
                    out var traceValues)
                ? traceValues.FirstOrDefault() ?? traceId
                : traceId;
            if (!response.IsSuccessStatusCode)
            {
                var detail = await ReadErrorAsync(response.Content, cancellationToken)
                    .ConfigureAwait(false);
                throw new ApiException(
                    detail?.Code ?? "HTTP_ERROR",
                    detail?.Message ?? $"Mac Core 返回 HTTP {(int)response.StatusCode}。",
                    detail?.Retryable ?? IsRetryableStatus(response.StatusCode),
                    detail?.TraceId ?? responseTrace,
                    (int)response.StatusCode);
            }

            var data = await ReadBoundedAsync(
                response.Content,
                MaxProviderResponseBytes,
                cancellationToken).ConfigureAwait(false);
            try
            {
                return JsonSerializer.Deserialize<T>(data, JsonOptions)
                    ?? throw new ApiException(
                        "EMPTY_RESPONSE",
                        "Mac Core 返回了空 Provider 响应。",
                        retryable: true,
                        responseTrace,
                        (int)response.StatusCode);
            }
            catch (JsonException exception)
            {
                throw new ApiException(
                    "INVALID_RESPONSE",
                    "Mac Core 返回了无法解析的 Provider 响应。",
                    retryable: true,
                    responseTrace,
                    (int)response.StatusCode,
                    exception);
            }
        }
        catch (ProviderResponseTooLargeException exception)
        {
            throw new ApiException(
                "RESPONSE_TOO_LARGE",
                "Mac Core 返回的 Provider 数据超过安全读取上限。",
                retryable: false,
                traceId,
                statusCode: 0,
                exception);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (OperationCanceledException exception)
        {
            throw new ApiException(
                "NETWORK_TIMEOUT",
                "读取 Provider 状态超时，请检查局域网和 Mac Core。",
                retryable: true,
                traceId,
                statusCode: 0,
                exception);
        }
        catch (HttpRequestException exception)
        {
            throw new ApiException(
                "NETWORK_ERROR",
                "无法连接 Mac Core Provider 接口。",
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
            throw new ProviderResponseTooLargeException();
        }

        await using var stream = await content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var buffer = new MemoryStream(capacity: Math.Min(maxBytes, 16 * 1024));
        var block = new byte[8 * 1024];
        var total = 0;
        while (true)
        {
            var read = await stream.ReadAsync(block.AsMemory(), cancellationToken)
                .ConfigureAwait(false);
            if (read == 0)
            {
                return buffer.ToArray();
            }
            total = checked(total + read);
            if (total > maxBytes)
            {
                throw new ProviderResponseTooLargeException();
            }
            await buffer.WriteAsync(block.AsMemory(0, read), cancellationToken)
                .ConfigureAwait(false);
        }
    }

    private static async Task<ApiErrorDetail?> ReadErrorAsync(
        HttpContent content,
        CancellationToken cancellationToken)
    {
        try
        {
            var data = await ReadBoundedAsync(content, MaxApiErrorBytes, cancellationToken)
                .ConfigureAwait(false);
            return JsonSerializer.Deserialize<ApiErrorEnvelope>(data, JsonOptions)?.Error;
        }
        catch (ProviderResponseTooLargeException)
        {
            return new ApiErrorDetail(
                "ERROR_RESPONSE_TOO_LARGE",
                "Mac Core 错误响应超过安全读取上限。",
                Retryable: false,
                TraceId: null);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static bool IsRetryableStatus(HttpStatusCode statusCode) =>
        statusCode is HttpStatusCode.RequestTimeout
            or HttpStatusCode.TooManyRequests
            or HttpStatusCode.BadGateway
            or HttpStatusCode.ServiceUnavailable
            or HttpStatusCode.GatewayTimeout;

    private static Uri EnsureTrailingSlash(Uri uri)
    {
        if (!uri.IsAbsoluteUri)
        {
            throw new ArgumentException("Mac Core 地址必须是绝对 URI。", nameof(uri));
        }
        return uri.AbsoluteUri.EndsWith('/')
            ? uri
            : new Uri(uri.AbsoluteUri + "/", UriKind.Absolute);
    }

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _httpClient.Dispose();
        }
        return ValueTask.CompletedTask;
    }

    private sealed class ProviderResponseTooLargeException : Exception;
}