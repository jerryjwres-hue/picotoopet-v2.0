using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>只访问固定 Return REST 合同的有界客户端，不支持上传、路径或命令。</summary>
public sealed class MacCoreReturnClient : IAsyncDisposable
{
    private const int MaxReturnResponseBytes = 128 * 1024;
    private const int MaxApiErrorBytes       = 64 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;

    /// <summary>使用调用方提供的 HttpClient 创建客户端，适合测试与依赖注入。</summary>
    public MacCoreReturnClient(HttpClient httpClient, Uri baseUri, string token)
        : this(httpClient, baseUri, token, ownsClient: false)
    {
    }

    private MacCoreReturnClient(
        HttpClient httpClient,
        Uri baseUri,
        string token,
        bool ownsClient)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _baseUri    = EnsureTrailingSlash(
            baseUri ?? throw new ArgumentNullException(nameof(baseUri)));
        _token = string.IsNullOrWhiteSpace(token)
            ? throw new ArgumentException("设备令牌不能为空。", nameof(token))
            : token;
        _ownsClient = ownsClient;
    }

    /// <summary>创建具有连接池和响应超时的长期 Return 客户端。</summary>
    public static MacCoreReturnClient Create(Uri baseUri, string token)
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime    = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout              = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer     = 8,
            AutomaticDecompression      = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
        return new MacCoreReturnClient(client, baseUri, token, ownsClient: true);
    }

    /// <summary>读取最多一百条 Return 安全投影。</summary>
    public Task<ReturnRecord[]> GetReturnsAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<ReturnRecord[]>(
            HttpMethod.Get,
            "api/v1/returns?limit=100",
            idempotencyKey: null,
            cancellationToken);

    /// <summary>读取一个 Return 的固定安全投影。</summary>
    public Task<ReturnRecord> GetReturnAsync(
        string returnId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(returnId);
        return SendAsync<ReturnRecord>(
            HttpMethod.Get,
            $"api/v1/returns/{Uri.EscapeDataString(returnId)}",
            idempotencyKey: null,
            cancellationToken);
    }

    /// <summary>为 approved Handoff 运行无请求正文的本地 Return 合同演练。</summary>
    public Task<ReturnRecord> RunSelfTestAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        return SendAsync<ReturnRecord>(
            HttpMethod.Post,
            $"api/v1/handoffs/{Uri.EscapeDataString(handoffId)}/returns/self-test",
            idempotencyKey,
            cancellationToken);
    }

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
                MaxReturnResponseBytes,
                cancellationToken).ConfigureAwait(false);
            try
            {
                return JsonSerializer.Deserialize<T>(data, JsonOptions)
                    ?? throw new ApiException(
                        "EMPTY_RESPONSE",
                        "Mac Core 返回了空 Return 响应。",
                        retryable: true,
                        responseTrace,
                        (int)response.StatusCode);
            }
            catch (JsonException exception)
            {
                throw new ApiException(
                    "INVALID_RESPONSE",
                    "Mac Core 返回了无法解析的 Return 响应。",
                    retryable: true,
                    responseTrace,
                    (int)response.StatusCode,
                    exception);
            }
        }
        catch (ReturnResponseTooLargeException exception)
        {
            throw new ApiException(
                "RESPONSE_TOO_LARGE",
                "Mac Core 返回的 Return 数据超过安全读取上限。",
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
                "读取 Return 超时，请检查局域网和 Mac Core。",
                retryable: true,
                traceId,
                statusCode: 0,
                exception);
        }
        catch (HttpRequestException exception)
        {
            throw new ApiException(
                "NETWORK_ERROR",
                "无法连接 Mac Core Return 接口。",
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
            throw new ReturnResponseTooLargeException();
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
                throw new ReturnResponseTooLargeException();
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
            var data = await ReadBoundedAsync(
                content,
                MaxApiErrorBytes,
                cancellationToken).ConfigureAwait(false);
            return JsonSerializer.Deserialize<ApiErrorEnvelope>(data, JsonOptions)?.Error;
        }
        catch (ReturnResponseTooLargeException)
        {
            return null;
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

    /// <summary>仅在客户端拥有连接池时释放底层资源。</summary>
    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _httpClient.Dispose();
        }
        return ValueTask.CompletedTask;
    }

    private sealed class ReturnResponseTooLargeException : Exception
    {
    }
}
