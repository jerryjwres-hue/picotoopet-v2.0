using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>业务自动化专用有界 REST 客户端；大文件只通过 4 MiB chunk API 传输。</summary>
public sealed class MacCoreBusinessAutomationClient : IAsyncDisposable
{
    public const int UploadChunkBytes = 4 * 1024 * 1024;
    private const int MaxJsonResponseBytes = 1024 * 1024;
    private const int MaxDownloadBytes = 8 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreBusinessAutomationClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreBusinessAutomationClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    public static MacCoreBusinessAutomationClient Create(MacCoreClientOptions options)
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
            Timeout = TimeSpan.FromMinutes(30),
        };
        return new MacCoreBusinessAutomationClient(client, options.Token, ownsClient: true);
    }

    public Task<BusinessUploadPrepareResponse> PrepareUploadAsync(
        BusinessUploadPrepareRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessUploadPrepareResponse>(
            HttpMethod.Post,
            "api/v1/business/work-packages/prepare",
            payload,
            cancellationToken);

    public async Task<BusinessUploadSessionRecord> UploadChunkAsync(
        string uploadSessionId,
        long offset,
        string sha256,
        ReadOnlyMemory<byte> payload,
        CancellationToken cancellationToken = default)
    {
        if (payload.IsEmpty || payload.Length > UploadChunkBytes)
        {
            throw new ArgumentOutOfRangeException(nameof(payload), "业务上传分块必须在 1 byte 到 4 MiB 之间。");
        }
        using var request = new HttpRequestMessage(
            HttpMethod.Put,
            $"api/v1/business/upload-sessions/{Uri.EscapeDataString(uploadSessionId)}/chunks?offset={offset}");
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", Guid.NewGuid().ToString("N"));
        request.Headers.TryAddWithoutValidation("X-Chunk-SHA256", sha256);
        request.Content = new ByteArrayContent(payload.ToArray());
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        return await SendPreparedAsync<BusinessUploadSessionRecord>(request, cancellationToken)
            .ConfigureAwait(false);
    }

    public Task<BusinessWorkPackageRecord> FinalizeUploadAsync(
        string uploadSessionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessWorkPackageRecord>(
            HttpMethod.Post,
            $"api/v1/business/upload-sessions/{Uri.EscapeDataString(uploadSessionId)}/finalize",
            null,
            cancellationToken);

    public Task<BusinessWorkPackageRecord[]> GetWorkPackagesAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessWorkPackageRecord[]>(
            HttpMethod.Get,
            "api/v1/business/work-packages?limit=200",
            null,
            cancellationToken);

    public Task<BusinessWorkPackageRecord> GetWorkPackageAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessWorkPackageRecord>(
            HttpMethod.Get,
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}",
            null,
            cancellationToken);

    public Task<BusinessWorkPackageRecord> CancelWorkPackageAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessWorkPackageRecord>(
            HttpMethod.Post,
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}/cancel",
            null,
            cancellationToken);

    public Task<BusinessResultPackageRecord?> GetResultAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessResultPackageRecord?>(
            HttpMethod.Get,
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}/result",
            null,
            cancellationToken);

    public Task<DeepAiHandoffRecord?> GetDeepAiHandoffAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiHandoffRecord?>(
            HttpMethod.Get,
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}/deep-ai-handoff",
            null,
            cancellationToken);

    public Task<byte[]> DownloadResultAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        DownloadBoundedAsync(
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}/result/download",
            cancellationToken);

    public Task<byte[]> DownloadDeepAiHandoffAsync(
        string workPackageId,
        CancellationToken cancellationToken = default) =>
        DownloadBoundedAsync(
            $"api/v1/business/work-packages/{Uri.EscapeDataString(workPackageId)}/deep-ai-handoff/download",
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
        return await SendPreparedAsync<T>(request, cancellationToken).ConfigureAwait(false);
    }

    private async Task<T> SendPreparedAsync<T>(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
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
            "BUSINESS_RESPONSE_TOO_LARGE",
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
            "BUSINESS_DOWNLOAD_TOO_LARGE",
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
                throw new ApiException(code, "业务自动化响应超过安全上限。", false, null, null);
            }
            bounded.Write(buffer, 0, read);
        }
        bounded.Position = 0;
        return bounded;
    }

    private static ApiException BuildHttpError(HttpStatusCode statusCode) =>
        new(
            "BUSINESS_HTTP_ERROR",
            $"Mac Core 业务自动化返回 HTTP {(int)statusCode}。",
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
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-BusinessBridge/2.3");
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
