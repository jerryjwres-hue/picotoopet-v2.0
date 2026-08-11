using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>2.3.21.1 Business Pipeline REST 客户端；只发送 Core 定义的有界编排身份。</summary>
public sealed class MacCoreBusinessPipelineClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 1024 * 1024;
    private const int MaxReturnArchiveBytes = 8 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreBusinessPipelineClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreBusinessPipelineClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    public static MacCoreBusinessPipelineClient Create(MacCoreClientOptions options)
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
            Timeout = TimeSpan.FromMinutes(20),
        };
        return new MacCoreBusinessPipelineClient(client, options.Token, ownsClient: true);
    }

    public Task<BusinessPipelineRunRecord[]> GetRunsAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessPipelineRunRecord[]>(
            HttpMethod.Get,
            "api/v1/business-pipeline/runs?limit=200",
            null,
            cancellationToken);

    public Task<BusinessPipelineRunRecord> CreateRunAsync(
        BusinessPipelineRunCreateRequest payload,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(payload);
        return SendJsonAsync<BusinessPipelineRunRecord>(
            HttpMethod.Post,
            "api/v1/business-pipeline/runs",
            payload,
            cancellationToken);
    }

    public Task<BusinessPipelineRunRecord> GetRunAsync(
        string pipelineRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessPipelineRunRecord>(
            HttpMethod.Get,
            $"api/v1/business-pipeline/runs/{Escape(pipelineRunId)}",
            null,
            cancellationToken);

    public Task<BusinessPipelineRunRecord> ReconcileAsync(
        string pipelineRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessPipelineRunRecord>(
            HttpMethod.Post,
            $"api/v1/business-pipeline/runs/{Escape(pipelineRunId)}/reconcile",
            null,
            cancellationToken);

    public Task<BusinessPipelineRunRecord> CancelAsync(
        string pipelineRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessPipelineRunRecord>(
            HttpMethod.Post,
            $"api/v1/business-pipeline/runs/{Escape(pipelineRunId)}/cancel",
            null,
            cancellationToken);

    public Task<BusinessReturnPackageRecord?> GetReturnPackageAsync(
        string pipelineRunId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<BusinessReturnPackageRecord?>(
            HttpMethod.Get,
            $"api/v1/business-pipeline/runs/{Escape(pipelineRunId)}/return-package",
            null,
            cancellationToken);

    public Task<byte[]> DownloadReturnPackageAsync(
        string pipelineRunId,
        CancellationToken cancellationToken = default) =>
        DownloadBoundedAsync(
            $"api/v1/business-pipeline/runs/{Escape(pipelineRunId)}/return-package/archive",
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
        using var bounded = await ReadBoundedAsync(stream, MaxJsonResponseBytes, cancellationToken)
            .ConfigureAwait(false);
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
        using var bounded = await ReadBoundedAsync(stream, MaxReturnArchiveBytes, cancellationToken)
            .ConfigureAwait(false);
        return bounded.ToArray();
    }

    private static async Task<MemoryStream> ReadBoundedAsync(
        Stream stream,
        int maximumBytes,
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
            if (bounded.Length + read > maximumBytes)
            {
                bounded.Dispose();
                throw new ApiException(
                    "BUSINESS_PIPELINE_RESPONSE_TOO_LARGE",
                    "Business Pipeline 响应超过安全上限。",
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
            "BUSINESS_PIPELINE_HTTP_ERROR",
            $"Mac Core Business Pipeline 返回 HTTP {(int)statusCode}。",
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
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-BusinessPipeline/2.3");
    }

    private static string Escape(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("Business Pipeline identity 不能为空。", nameof(value));
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
