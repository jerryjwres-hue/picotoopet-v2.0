using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>2.3.20.1 Production REST 客户端；只发送 Core 定义的有界状态与执行证据。</summary>
public sealed class MacCoreProductionClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 4 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreProductionClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreProductionClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    /// <summary>从现有 Mac Core 配对信息创建客户端；不接受 ComfyUI endpoint。</summary>
    public static MacCoreProductionClient Create(MacCoreClientOptions options)
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
        return new MacCoreProductionClient(client, options.Token, ownsClient: true);
    }

    public Task<ProductionEligibleCreativeRecord[]> GetEligibleAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionEligibleCreativeRecord[]>(
            HttpMethod.Get,
            "api/v1/production/eligible",
            null,
            cancellationToken);

    public Task<ProductionJobRecord[]> GetJobsAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionJobRecord[]>(
            HttpMethod.Get,
            "api/v1/production/jobs?limit=200",
            null,
            cancellationToken);

    public Task<ProductionJobRecord> CreateJobAsync(
        ProductionJobCreateRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionJobRecord>(
            HttpMethod.Post,
            "api/v1/production/jobs",
            payload,
            cancellationToken);

    public Task<ProductionPlanRecord> GetPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionPlanRecord>(
            HttpMethod.Get,
            $"api/v1/production/jobs/{Escape(productionJobId)}/plan",
            null,
            cancellationToken);

    public Task<ProductionClaimRecord> ClaimAsync(
        string productionJobId,
        string executorId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionClaimRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/claim",
            new { executor_id = executorId },
            cancellationToken);

    public Task<ProductionJobRecord> HeartbeatAsync(
        string productionJobId,
        string executorId,
        string leaseToken,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionJobRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/heartbeat",
            new { executor_id = executorId, lease_token = leaseToken },
            cancellationToken);

    public Task<ProductionTaskRecord> MarkAttemptAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskAttemptRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionTaskRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/tasks/{Escape(productionTaskId)}/attempt",
            payload,
            cancellationToken);

    public Task<ProductionTaskRecord> CommitResultAsync(
        string productionJobId,
        string productionTaskId,
        ProductionTaskCommitRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionTaskRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/tasks/{Escape(productionTaskId)}/result",
            payload,
            cancellationToken);

    public Task<ProductionJobRecord> CancelAsync(
        string productionJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionJobRecord>(
            HttpMethod.Post,
            $"api/v1/production/jobs/{Escape(productionJobId)}/cancel",
            null,
            cancellationToken);

    public Task<ProductionPackageRecord?> GetPackageAsync(
        string productionJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProductionPackageRecord?>(
            HttpMethod.Get,
            $"api/v1/production/jobs/{Escape(productionJobId)}/package",
            null,
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
        return result!;
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
                    "PRODUCTION_RESPONSE_TOO_LARGE",
                    "Production 响应超过安全上限。",
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
            "PRODUCTION_HTTP_ERROR",
            $"Mac Core Production 返回 HTTP {(int)statusCode}。",
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
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-Production/2.3");
    }

    private static string Escape(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("Production identity 不能为空。", nameof(value));
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
