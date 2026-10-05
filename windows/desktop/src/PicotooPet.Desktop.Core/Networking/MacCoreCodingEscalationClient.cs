using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>只读取固定 Frugal decision GET，不提供任何 Provider 写入口。</summary>
public sealed class MacCoreCodingEscalationClient : IAsyncDisposable
{
    private const int MaxResponseBytes = 128 * 1024;
    private const int MaxApiErrorBytes = 64 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly bool _ownsClient;

    public MacCoreCodingEscalationClient(HttpClient httpClient, Uri baseUri, string token)
        : this(httpClient, baseUri, token, ownsClient: false)
    {
    }

    private MacCoreCodingEscalationClient(
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

    public static MacCoreCodingEscalationClient Create(Uri baseUri, string token)
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer = 4,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
        return new MacCoreCodingEscalationClient(client, baseUri, token, ownsClient: true);
    }

    /// <summary>按 Goal ID 读取 Core 已持久化的不可变仲裁决策。</summary>
    public Task<CodingEscalationDecisionRecord> GetDecisionAsync(
        string goalId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        return SendAsync(
            $"api/v1/coding-escalations/{Uri.EscapeDataString(goalId)}/decision",
            cancellationToken);
    }

    private async Task<CodingEscalationDecisionRecord> SendAsync(
        string relativeUri,
        CancellationToken cancellationToken)
    {
        var traceId = Guid.NewGuid().ToString("N");
        using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(_baseUri, relativeUri));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);

        try
        {
            using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
            var responseTrace = response.Headers.TryGetValues("X-Picotoo-Trace-Id", out var values)
                ? values.FirstOrDefault() ?? traceId
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

            var data = await ReadBoundedAsync(response.Content, MaxResponseBytes, cancellationToken)
                .ConfigureAwait(false);
            try
            {
                return JsonSerializer.Deserialize<CodingEscalationDecisionRecord>(data, JsonOptions)
                    ?? throw new ApiException(
                        "EMPTY_RESPONSE",
                        "Mac Core 返回了空 Coding Escalation 响应。",
                        retryable: true,
                        responseTrace,
                        (int)response.StatusCode);
            }
            catch (JsonException exception)
            {
                throw new ApiException(
                    "INVALID_RESPONSE",
                    "Mac Core 返回了无法解析的 Coding Escalation 响应。",
                    retryable: true,
                    responseTrace,
                    (int)response.StatusCode,
                    exception);
            }
        }
        catch (ResponseTooLargeException exception)
        {
            throw new ApiException(
                "RESPONSE_TOO_LARGE",
                "Mac Core 返回的 Coding Escalation 数据超过安全读取上限。",
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
                "读取 Coding Escalation 决策超时，请检查局域网和 Mac Core。",
                retryable: true,
                traceId,
                statusCode: 0,
                exception);
        }
        catch (HttpRequestException exception)
        {
            throw new ApiException(
                "NETWORK_ERROR",
                "无法连接 Mac Core Coding Escalation 接口。",
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
            throw new ResponseTooLargeException();
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
                throw new ResponseTooLargeException();
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
        catch (ResponseTooLargeException)
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

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _httpClient.Dispose();
        }
        return ValueTask.CompletedTask;
    }

    private sealed class ResponseTooLargeException : Exception
    {
    }
}
