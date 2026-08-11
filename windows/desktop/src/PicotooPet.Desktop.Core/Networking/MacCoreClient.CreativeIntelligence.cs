using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Creative Intelligence 有界 REST 客户端；没有模型、Prompt、Endpoint 或工具配置面。</summary>
public sealed class MacCoreCreativeIntelligenceClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 1024 * 1024;
    private const int MaxDownloadBytes = 8 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreCreativeIntelligenceClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreCreativeIntelligenceClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    public static MacCoreCreativeIntelligenceClient Create(MacCoreClientOptions options)
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
            Timeout = TimeSpan.FromMinutes(10),
        };
        return new MacCoreCreativeIntelligenceClient(client, options.Token, ownsClient: true);
    }

    public Task<CreativeEligibleSourceRecord[]> GetEligibleSourcesAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativeEligibleSourceRecord[]>(
            HttpMethod.Get,
            "api/v1/creative/eligible-sources",
            null,
            cancellationToken);

    public Task<CreativeJobRecord> CreateJobAsync(
        CreativeJobCreateRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativeJobRecord>(
            HttpMethod.Post,
            "api/v1/creative/jobs",
            payload,
            cancellationToken);

    public Task<CreativeJobRecord[]> GetJobsAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativeJobRecord[]>(
            HttpMethod.Get,
            "api/v1/creative/jobs?limit=200",
            null,
            cancellationToken);

    public Task<CreativeJobRecord> CancelJobAsync(
        string creativeJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativeJobRecord>(
            HttpMethod.Post,
            $"api/v1/creative/jobs/{Uri.EscapeDataString(creativeJobId)}/cancel",
            null,
            cancellationToken);

    public Task<CreativePackageRecord?> GetPackageAsync(
        string creativeJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativePackageRecord?>(
            HttpMethod.Get,
            $"api/v1/creative/jobs/{Uri.EscapeDataString(creativeJobId)}/package",
            null,
            cancellationToken);

    public Task<CreativeDeepAiHandoffRecord?> GetHandoffAsync(
        string creativeJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<CreativeDeepAiHandoffRecord?>(
            HttpMethod.Get,
            $"api/v1/creative/jobs/{Uri.EscapeDataString(creativeJobId)}/deep-ai-handoff",
            null,
            cancellationToken);

    public Task<byte[]> DownloadPackageAsync(
        string creativeJobId,
        CancellationToken cancellationToken = default) =>
        DownloadBoundedAsync(
            $"api/v1/creative/jobs/{Uri.EscapeDataString(creativeJobId)}/package/download",
            cancellationToken);

    public Task<byte[]> DownloadHandoffAsync(
        string creativeJobId,
        CancellationToken cancellationToken = default) =>
        DownloadBoundedAsync(
            $"api/v1/creative/jobs/{Uri.EscapeDataString(creativeJobId)}/deep-ai-handoff/download",
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
        using var bounded = await ReadBoundedAsync(
            stream,
            MaxJsonResponseBytes,
            "CREATIVE_RESPONSE_TOO_LARGE",
            cancellationToken).ConfigureAwait(false);
        var result = await JsonSerializer.DeserializeAsync<T>(bounded, JsonOptions, cancellationToken)
            .ConfigureAwait(false);
        return result!;
    }

    private async Task<byte[]> DownloadBoundedAsync(
        string relativeUri,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, relativeUri);
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", Guid.NewGuid().ToString("N"));
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
        using var bounded = await ReadBoundedAsync(
            stream,
            MaxDownloadBytes,
            "CREATIVE_DOWNLOAD_TOO_LARGE",
            cancellationToken).ConfigureAwait(false);
        return bounded.ToArray();
    }

    private static async Task<MemoryStream> ReadBoundedAsync(
        Stream stream,
        int maxBytes,
        string code,
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
            if (bounded.Length + read > maxBytes)
            {
                bounded.Dispose();
                throw new ApiException(code, "Creative Intelligence 响应超过安全上限。", false, null, 0);
            }
            bounded.Write(buffer, 0, read);
        }
        bounded.Position = 0;
        return bounded;
    }

    private static ApiException BuildHttpError(HttpStatusCode statusCode) =>
        new(
            "CREATIVE_HTTP_ERROR",
            $"Mac Core Creative Intelligence 返回 HTTP {(int)statusCode}。",
            statusCode is HttpStatusCode.RequestTimeout
                or HttpStatusCode.TooManyRequests
                or HttpStatusCode.BadGateway
                or HttpStatusCode.ServiceUnavailable
                or HttpStatusCode.GatewayTimeout,
            null,
            (int)statusCode);

    private void ConfigureHeaders(string token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }
        _client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        _client.DefaultRequestHeaders.Accept.Clear();
        _client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-CreativeIntelligence/2.3");
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
