using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>24.1 Controlled Shadow 客户端；请求面只包含 candidate identity 与闭合 review action。</summary>
public sealed class MacCoreQualityShadowClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 2 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreQualityShadowClient(HttpClient client, string token)
        : this(client, token, ownsClient: false)
    {
    }

    private MacCoreQualityShadowClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = ownsClient;
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }
        _client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        _client.DefaultRequestHeaders.Accept.Clear();
        _client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-Shadow/2.3.25.1");
    }

    public static MacCoreQualityShadowClient Create(MacCoreClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout = options.ConnectTimeout,
            MaxConnectionsPerServer = 4,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = EnsureTrailingSlash(options.BaseUri),
            Timeout = options.RequestTimeout,
        };
        return new MacCoreQualityShadowClient(client, options.Token, ownsClient: true);
    }

    public Task<QualityShadowRunRecord> CreateAsync(
        QualityShadowRunCreateRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityShadowRunRecord>(
            HttpMethod.Post,
            "api/v1/deep-ai/shadow-runs",
            payload,
            cancellationToken);

    public Task<QualityShadowRunRecord[]> GetRunsAsync(
        string? candidateId = null,
        CancellationToken cancellationToken = default)
    {
        var path = string.IsNullOrWhiteSpace(candidateId)
            ? "api/v1/deep-ai/shadow-runs?limit=200"
            : $"api/v1/deep-ai/shadow-runs?candidate_id={Escape(candidateId)}&limit=200";
        return SendJsonAsync<QualityShadowRunRecord[]>(HttpMethod.Get, path, null, cancellationToken);
    }

    public Task<QualityShadowRunRecord> GetRunAsync(
        string shadowRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityShadowRunRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/shadow-runs/{Escape(shadowRunId)}",
            null,
            cancellationToken);

    public Task<QualityShadowRunRecord> ReconcileAsync(
        string shadowRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityShadowRunRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/shadow-runs/{Escape(shadowRunId)}/reconcile",
            new { },
            cancellationToken);

    public Task<QualityShadowArmMetricRecord[]> GetMetricsAsync(
        string shadowRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityShadowArmMetricRecord[]>(
            HttpMethod.Get,
            $"api/v1/deep-ai/shadow-runs/{Escape(shadowRunId)}/metrics",
            null,
            cancellationToken);

    public Task<QualityShadowReviewRecord> ReviewAsync(
        string shadowRunId,
        QualityShadowReviewRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityShadowReviewRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/shadow-runs/{Escape(shadowRunId)}/review",
            payload,
            cancellationToken);

    private async Task<T> SendJsonAsync<T>(
        HttpMethod method,
        string relativeUri,
        object? payload,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUri);
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", Guid.NewGuid().ToString("N"));
        if (payload is not null)
        {
            request.Content = JsonContent.Create(payload, options: JsonOptions);
        }
        using var response = await _client.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw BuildHttpError(response.StatusCode);
        }
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var bounded = await ReadBoundedAsync(stream, cancellationToken).ConfigureAwait(false);
        var result = await JsonSerializer.DeserializeAsync<T>(bounded, JsonOptions, cancellationToken)
            .ConfigureAwait(false);
        return result ?? throw new InvalidDataException("Shadow response body was empty.");
    }

    private static async Task<MemoryStream> ReadBoundedAsync(
        Stream stream,
        CancellationToken cancellationToken)
    {
        var bounded = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (bounded.Length + read > MaxJsonResponseBytes)
            {
                bounded.Dispose();
                throw new ApiException(
                    "QUALITY_SHADOW_RESPONSE_TOO_LARGE",
                    "Shadow 响应超过安全上限。",
                    false,
                    null,
                    0);
            }
            bounded.Write(buffer, 0, read);
        }
        bounded.Position = 0;
        return bounded;
    }

    private static ApiException BuildHttpError(HttpStatusCode statusCode) =>
        new(
            "QUALITY_SHADOW_HTTP_ERROR",
            $"Mac Core Shadow 返回 HTTP {(int)statusCode}。",
            statusCode is HttpStatusCode.RequestTimeout
                or HttpStatusCode.TooManyRequests
                or HttpStatusCode.BadGateway
                or HttpStatusCode.ServiceUnavailable
                or HttpStatusCode.GatewayTimeout,
            null,
            (int)statusCode);

    private static string Escape(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("Shadow identity 不能为空。", nameof(value));
        }
        return Uri.EscapeDataString(value);
    }

    private static Uri EnsureTrailingSlash(Uri uri) =>
        uri.AbsoluteUri.EndsWith('/') ? uri : new Uri(uri.AbsoluteUri + "/", UriKind.Absolute);

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _client.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}
