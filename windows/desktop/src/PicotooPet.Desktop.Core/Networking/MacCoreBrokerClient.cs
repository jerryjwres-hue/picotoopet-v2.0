using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>只访问固定 Broker Session REST 合同的有界客户端。</summary>
public sealed class MacCoreBrokerClient : IAsyncDisposable
{
    private const int MaxBrokerResponseBytes = 128 * 1024;
    private const int MaxApiErrorBytes       = 64 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling      = JsonUnmappedMemberHandling.Disallow,
    };

    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;

    /// <summary>使用调用方提供的 HttpClient 创建客户端，适合原生 smoke 与依赖注入。</summary>
    public MacCoreBrokerClient(HttpClient httpClient, Uri baseUri, string token)
        : this(httpClient, baseUri, token, ownsClient: false)
    {
    }

    private MacCoreBrokerClient(
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

    /// <summary>创建具有连接池和固定响应超时的长期 Broker 客户端。</summary>
    public static MacCoreBrokerClient Create(Uri baseUri, string token)
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
        return new MacCoreBrokerClient(client, baseUri, token, ownsClient: true);
    }

    /// <summary>读取最多一百条 Broker Session 安全投影。</summary>
    public Task<BrokerSessionRecord[]> GetSessionsAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<BrokerSessionRecord[]>(
            () => CreateRequest(HttpMethod.Get, "api/v1/broker-sessions?limit=100"),
            retryWriteOnce: false,
            cancellationToken);

    /// <summary>读取一个 Broker Session 安全投影。</summary>
    public Task<BrokerSessionRecord> GetSessionAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        ValidateIdentifier(sessionId, nameof(sessionId));
        return SendAsync<BrokerSessionRecord>(
            () => CreateRequest(
                HttpMethod.Get,
                $"api/v1/broker-sessions/{Uri.EscapeDataString(sessionId)}"),
            retryWriteOnce: false,
            cancellationToken);
    }

    /// <summary>为 approved Handoff 幂等预留固定 Mock Broker Session。</summary>
    public Task<BrokerSessionCreateResult> ReserveMockAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken = default)
    {
        ValidateIdentifier(handoffId, nameof(handoffId));
        ValidateIdempotencyKey(idempotencyKey);
        return SendAsync<BrokerSessionCreateResult>(
            () => CreateWriteRequest(
                $"api/v1/handoffs/{Uri.EscapeDataString(handoffId)}/broker-sessions/mock",
                idempotencyKey),
            retryWriteOnce: true,
            cancellationToken);
    }

    /// <summary>记录固定子进程即将启动。</summary>
    public Task<BrokerSessionRecord> StartAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendStateCommandAsync(sessionId, "start", idempotencyKey, cancellationToken);

    /// <summary>记录 Broker Session 取消事实。</summary>
    public Task<BrokerSessionRecord> CancelAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendStateCommandAsync(sessionId, "cancel", idempotencyKey, cancellationToken);

    /// <summary>提交严格 JSON Return；capability 只存在于本次专用 Header。</summary>
    public Task<BrokerSessionRecord> SubmitReturnAsync(
        string sessionId,
        MockBrokerReturnEnvelope envelope,
        string capability,
        string idempotencyKey,
        CancellationToken cancellationToken = default)
    {
        ValidateIdentifier(sessionId, nameof(sessionId));
        ArgumentNullException.ThrowIfNull(envelope);
        ValidateCapability(capability);
        ValidateIdempotencyKey(idempotencyKey);
        return SendAsync<BrokerSessionRecord>(
            () =>
            {
                var request = CreateWriteRequest(
                    $"api/v1/broker-sessions/{Uri.EscapeDataString(sessionId)}/return",
                    idempotencyKey);
                request.Headers.TryAddWithoutValidation(
                    "X-Picotoo-Broker-Session",
                    capability);
                request.Content = JsonContent.Create(envelope, options: JsonOptions);
                return request;
            },
            retryWriteOnce: true,
            cancellationToken);
    }

    private Task<BrokerSessionRecord> SendStateCommandAsync(
        string sessionId,
        string command,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ValidateIdentifier(sessionId, nameof(sessionId));
        ValidateIdempotencyKey(idempotencyKey);
        if (command is not "start" and not "cancel")
        {
            throw new ArgumentOutOfRangeException(nameof(command));
        }
        return SendAsync<BrokerSessionRecord>(
            () => CreateWriteRequest(
                $"api/v1/broker-sessions/{Uri.EscapeDataString(sessionId)}/{command}",
                idempotencyKey),
            retryWriteOnce: true,
            cancellationToken);
    }

    private async Task<T> SendAsync<T>(
        Func<HttpRequestMessage> requestFactory,
        bool retryWriteOnce,
        CancellationToken cancellationToken)
    {
        var maximumAttempts = retryWriteOnce ? 2 : 1;
        ApiException? retryableApiError = null;
        HttpRequestException? retryableNetworkError = null;
        for (var attempt = 0; attempt < maximumAttempts; attempt++)
        {
            using var request = requestFactory();
            var traceId = Guid.NewGuid().ToString("N");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
            request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);
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
                    var exception = new ApiException(
                        detail?.Code ?? "HTTP_ERROR",
                        detail?.Message ?? $"Mac Core 返回 HTTP {(int)response.StatusCode}。",
                        detail?.Retryable ?? IsRetryableStatus(response.StatusCode),
                        detail?.TraceId ?? responseTrace,
                        (int)response.StatusCode);
                    if (attempt + 1 < maximumAttempts && exception.Retryable)
                    {
                        retryableApiError = exception;
                        continue;
                    }
                    throw exception;
                }

                var data = await ReadBoundedAsync(
                    response.Content,
                    MaxBrokerResponseBytes,
                    cancellationToken).ConfigureAwait(false);
                try
                {
                    return JsonSerializer.Deserialize<T>(data, JsonOptions)
                        ?? throw new ApiException(
                            "EMPTY_RESPONSE",
                            "Mac Core 返回了空 Broker 响应。",
                            retryable: true,
                            responseTrace,
                            (int)response.StatusCode);
                }
                catch (JsonException exception)
                {
                    throw new ApiException(
                        "INVALID_RESPONSE",
                        "Mac Core 返回了无法解析的 Broker 响应。",
                        retryable: false,
                        responseTrace,
                        (int)response.StatusCode,
                        exception);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (HttpRequestException exception) when (attempt + 1 < maximumAttempts)
            {
                retryableNetworkError = exception;
            }
            catch (BrokerResponseTooLargeException exception)
            {
                throw new ApiException(
                    "RESPONSE_TOO_LARGE",
                    "Mac Core 返回的 Broker 数据超过安全读取上限。",
                    retryable: false,
                    traceId,
                    statusCode: 0,
                    exception);
            }
        }

        if (retryableApiError is not null)
        {
            throw retryableApiError;
        }
        throw new ApiException(
            "NETWORK_ERROR",
            "无法连接 Mac Core Broker 接口。",
            retryable: true,
            Guid.NewGuid().ToString("N"),
            retryableNetworkError?.StatusCode is null
                ? 0
                : (int)retryableNetworkError.StatusCode.Value,
            retryableNetworkError);
    }

    private HttpRequestMessage CreateRequest(HttpMethod method, string relativeUri) =>
        new(method, new Uri(_baseUri, relativeUri));

    private HttpRequestMessage CreateWriteRequest(
        string relativeUri,
        string idempotencyKey)
    {
        var request = CreateRequest(HttpMethod.Post, relativeUri);
        request.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
        return request;
    }

    private static async Task<byte[]> ReadBoundedAsync(
        HttpContent content,
        int maxBytes,
        CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is long length && length > maxBytes)
        {
            throw new BrokerResponseTooLargeException();
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
                throw new BrokerResponseTooLargeException();
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
        catch (BrokerResponseTooLargeException)
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

    private static void ValidateIdentifier(string value, string parameterName)
    {
        if (!Guid.TryParseExact(value, "D", out _))
        {
            throw new ArgumentException("资源 ID 必须是规范 UUID。", parameterName);
        }
    }

    private static void ValidateIdempotencyKey(string value)
    {
        if (string.IsNullOrWhiteSpace(value)
            || value.Length > 200
            || value.Any(character => character < 33))
        {
            throw new ArgumentException("幂等键不符合固定安全格式。", nameof(value));
        }
    }

    private static void ValidateCapability(string value)
    {
        if (value.Length != 64 || value.Any(character =>
                character is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
        {
            throw new ArgumentException("Broker capability 格式无效。", nameof(value));
        }
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

    private sealed class BrokerResponseTooLargeException : Exception
    {
    }
}
