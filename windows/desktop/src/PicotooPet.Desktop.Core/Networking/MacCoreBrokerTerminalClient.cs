using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Broker 子进程只允许提交 timeout 或 fail 两种固定终态。</summary>
public enum BrokerTerminalAction
{
    Timeout = 1,
    Fail    = 2,
}

/// <summary>提交固定 Broker 终态的有界客户端；不接受错误正文、命令或路径。</summary>
public sealed class MacCoreBrokerTerminalClient : IAsyncDisposable
{
    private const int MaxResponseBytes = 128 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling      = JsonUnmappedMemberHandling.Disallow,
    };

    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;

    /// <summary>使用调用方 HttpClient 创建测试客户端。</summary>
    public MacCoreBrokerTerminalClient(HttpClient httpClient, Uri baseUri, string token)
        : this(httpClient, baseUri, token, ownsClient: false)
    {
    }

    private MacCoreBrokerTerminalClient(
        HttpClient httpClient,
        Uri baseUri,
        string token,
        bool ownsClient)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _baseUri    = EnsureTrailingSlash(baseUri ?? throw new ArgumentNullException(nameof(baseUri)));
        _token      = string.IsNullOrWhiteSpace(token)
            ? throw new ArgumentException("设备令牌不能为空。", nameof(token))
            : token;
        _ownsClient = ownsClient;
    }

    /// <summary>创建具有固定连接和响应时限的长期客户端。</summary>
    public static MacCoreBrokerTerminalClient Create(Uri baseUri, string token)
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime    = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout              = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer     = 4,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
        return new MacCoreBrokerTerminalClient(client, baseUri, token, ownsClient: true);
    }

    /// <summary>使用同一幂等键最多尝试两次固定终态提交。</summary>
    public async Task<BrokerSessionRecord> SetTerminalAsync(
        string sessionId,
        BrokerTerminalAction action,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        if (!Guid.TryParseExact(sessionId, "D", out _))
        {
            throw new ArgumentException("Broker Session ID 必须是规范 UUID。", nameof(sessionId));
        }
        if (string.IsNullOrWhiteSpace(idempotencyKey)
            || idempotencyKey.Length > 200
            || idempotencyKey.Any(character => character < 33))
        {
            throw new ArgumentException("幂等键不符合固定安全格式。", nameof(idempotencyKey));
        }
        var segment = action switch
        {
            BrokerTerminalAction.Timeout => "timeout",
            BrokerTerminalAction.Fail    => "fail",
            _ => throw new ArgumentOutOfRangeException(nameof(action)),
        };

        HttpRequestException? networkError = null;
        for (var attempt = 0; attempt < 2; attempt++)
        {
            using var request = new HttpRequestMessage(
                HttpMethod.Post,
                new Uri(
                    _baseUri,
                    $"api/v1/broker-sessions/{Uri.EscapeDataString(sessionId)}/{segment}"));
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
            request.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
            request.Headers.TryAddWithoutValidation(
                "X-Picotoo-Trace-Id",
                Guid.NewGuid().ToString("N"));
            try
            {
                using var response = await _httpClient.SendAsync(
                    request,
                    HttpCompletionOption.ResponseHeadersRead,
                    cancellationToken).ConfigureAwait(false);
                if (!response.IsSuccessStatusCode)
                {
                    if (attempt == 0 && IsRetryable(response.StatusCode))
                    {
                        continue;
                    }
                    throw new ApiException(
                        "BROKER_TERMINAL_UPDATE_FAILED",
                        "Mac Core 拒绝了固定 Broker 终态更新。",
                        retryable: IsRetryable(response.StatusCode),
                        traceId: response.Headers.TryGetValues(
                                "X-Picotoo-Trace-Id",
                                out var values)
                            ? values.FirstOrDefault()
                            : null,
                        statusCode: (int)response.StatusCode);
                }

                var data = await ReadBoundedAsync(response.Content, cancellationToken)
                    .ConfigureAwait(false);
                try
                {
                    return JsonSerializer.Deserialize<BrokerSessionRecord>(data, JsonOptions)
                        ?? throw new JsonException("Broker terminal response is empty.");
                }
                catch (JsonException exception)
                {
                    throw new ApiException(
                        "INVALID_RESPONSE",
                        "Mac Core 返回了无法解析的 Broker 终态响应。",
                        retryable: false,
                        traceId: null,
                        statusCode: (int)response.StatusCode,
                        innerException: exception);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (HttpRequestException exception)
            {
                networkError = exception;
                if (attempt == 0)
                {
                    continue;
                }
                break;
            }
        }

        throw new ApiException(
            "NETWORK_ERROR",
            "无法连接 Mac Core Broker 终态接口。",
            retryable: true,
            traceId: null,
            statusCode: 0,
            innerException: networkError);
    }

    private static async Task<byte[]> ReadBoundedAsync(
        HttpContent content,
        CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is long length && length > MaxResponseBytes)
        {
            throw new ApiException(
                "RESPONSE_TOO_LARGE",
                "Mac Core Broker 终态响应超过安全上限。",
                retryable: false,
                traceId: null,
                statusCode: 0);
        }
        await using var stream = await content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var buffer = new MemoryStream(capacity: 16 * 1024);
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
            if (total > MaxResponseBytes)
            {
                throw new ApiException(
                    "RESPONSE_TOO_LARGE",
                    "Mac Core Broker 终态响应超过安全上限。",
                    retryable: false,
                    traceId: null,
                    statusCode: 0);
            }
            await buffer.WriteAsync(block.AsMemory(0, read), cancellationToken)
                .ConfigureAwait(false);
        }
    }

    private static bool IsRetryable(HttpStatusCode statusCode) =>
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
}
