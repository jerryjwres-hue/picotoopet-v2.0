using System.Diagnostics;
using System.Security.Cryptography;
using System.Net.Sockets;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>复用连接池、幂等键和 Trace Header 的 Mac Core REST 客户端。</summary>
public sealed class MacCoreClient : IAsyncDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;
    private readonly HttpClient? _frameTransferClient;
    private readonly bool _ownsClient;

    /// <summary>请求完成或失败时发布本机单调时钟测得的延迟。</summary>
    public event EventHandler<RequestMeasurement>? RequestMeasured;

    /// <summary>使用共享 HttpClient 创建客户端，适合测试与依赖注入。</summary>
    public MacCoreClient(HttpClient httpClient, string token)
    {
        _httpClient = httpClient;
        _frameTransferClient = null; // 注入的测试客户端仍复用相同 HttpMessageHandler。
        _ownsClient = false;
        ConfigureHeaders(_httpClient, token);
    }

    private MacCoreClient(
        HttpClient httpClient, string token, bool ownsClient, HttpClient? frameTransferClient)
    {
        _httpClient = httpClient;
        _frameTransferClient = frameTransferClient;
        _ownsClient = ownsClient;
        ConfigureHeaders(_httpClient, token);
        if (_frameTransferClient is not null)
        {
            ConfigureHeaders(_frameTransferClient, token);
        }
    }

    /// <summary>创建具有连接池、DNS 更新和压缩支持的长期客户端。</summary>
    public static MacCoreClient Create(MacCoreClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.Token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(options));
        }

        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime      = options.PooledConnectionLifetime,
            PooledConnectionIdleTimeout   = TimeSpan.FromMinutes(2),
            ConnectTimeout                = options.ConnectTimeout,
            MaxConnectionsPerServer       = 16,
            AutomaticDecompression        = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            EnableMultipleHttp2Connections = false,
            // 不跟随跳转到不可信域名，特别是持有设备 Bearer 的私有素材下载。
            AllowAutoRedirect            = false,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = EnsureTrailingSlash(options.BaseUri),
            Timeout     = options.RequestTimeout,
        };
        // 素材可能达到 128 MiB；单独的传输连接池不能继承控制指令 5s 超时。
        var transferHandler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            ConnectTimeout           = options.ConnectTimeout,
            AllowAutoRedirect        = false,
            MaxConnectionsPerServer  = 2,
        };
        var transfer = new HttpClient(transferHandler, disposeHandler: true)
        {
            BaseAddress = EnsureTrailingSlash(options.BaseUri),
            Timeout     = TimeSpan.FromMinutes(2),
        };
        return new MacCoreClient(client, options.Token, ownsClient: true, transfer);
    }

    /// <summary>读取公共健康状态。</summary>
    public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<HealthResponse>(HttpMethod.Get, "api/v1/health", null, "health", null, cancellationToken);

    /// <summary>读取服务与队列聚合状态。</summary>
    public Task<StatusResponse> GetStatusAsync(CancellationToken cancellationToken = default) =>
        SendAsync<StatusResponse>(HttpMethod.Get, "api/v1/status", null, "status", null, cancellationToken);

    /// <summary>读取最近的用户任务快照，排除性能诊断任务以减少带宽和状态内存。</summary>
    public Task<TaskRecord[]> GetTasksAsync(CancellationToken cancellationToken = default) =>
        SendAsync<TaskRecord[]>(
            HttpMethod.Get,
            "api/v1/tasks?exclude_resource_tag=phase2-diagnostic&limit=500",
            null,
            "tasks.list",
            null,
            cancellationToken);

    /// <summary>幂等创建任务；重试必须复用相同 Idempotency-Key。</summary>
    public Task<TaskRecord> CreateTaskAsync(
        TaskCreateRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken = default) =>
        SendAsync<TaskRecord>(
            HttpMethod.Post,
            "api/v1/tasks",
            request,
            "tasks.create",
            idempotencyKey,
            cancellationToken);

    /// <summary>取消尚未进入不可逆终态的任务。</summary>
    public Task<TaskRecord> CancelTaskAsync(
        string taskId,
        CancellationToken cancellationToken = default) =>
        SendAsync<TaskRecord>(
            HttpMethod.Post,
            $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/cancel",
            null,
            "tasks.cancel",
            null,
            cancellationToken);

    /// <summary>为失败或取消任务创建新的子任务。</summary>
    public Task<TaskRecord> RetryTaskAsync(
        string taskId,
        CancellationToken cancellationToken = default) =>
        SendAsync<TaskRecord>(
            HttpMethod.Post,
            $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/retry",
            null,
            "tasks.retry",
            null,
            cancellationToken);

    /// <summary>只读验证来自云端 LLM 的 StoryPack；不会创建任何生产任务。</summary>
    /// <summary>生成一次性手机只读配对码，不向手机传递 Windows 设备凭证。</summary>
    public Task<JsonElement> IssueMobilePairingAsync(
        CancellationToken cancellationToken = default) =>
        SendAsync<JsonElement>(
            HttpMethod.Post,
            "api/v1/mobile/pairing",
            null,
            "mobile.pairing",
            null,
            cancellationToken);

    public Task<JsonElement> PreviewStoryPackAsync(
        JsonElement storyPack, CancellationToken cancellationToken = default) =>
        SendAsync<JsonElement>(
            HttpMethod.Post,
            "api/v1/studio/storypacks/preview",
            storyPack,
            "studio.storypack.preview",
            null,
            cancellationToken);

    public Task<EpisodeSummary[]> GetEpisodesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<EpisodeSummary[]>(HttpMethod.Get, "api/v1/episodes",
            null, "episodes.list", null, cancellationToken);

    public Task<EpisodeImportResult> ImportBatchAsync(JsonElement manifest, CancellationToken cancellationToken) =>
        SendAsync<EpisodeImportResult>(HttpMethod.Post, "api/v1/episodes/import",
            manifest, "episodes.import", null, cancellationToken);

    public Task<EpisodeReview> GetEpisodeReviewAsync(
        string episodeId, CancellationToken cancellationToken = default) =>
        SendAsync<EpisodeReview>(HttpMethod.Get,
            $"api/v1/episodes/{Uri.EscapeDataString(episodeId)}/review",
            null, "episodes.review", null, cancellationToken);

    public Task<JsonElement> DecideArtifactAsync(
        string artifactId, ArtifactDecisionRequest decision, CancellationToken cancellationToken = default) =>
        SendAsync<JsonElement>(HttpMethod.Post,
            $"api/v1/artifacts/{Uri.EscapeDataString(artifactId)}/decision",
            decision, "artifacts.decision", null, cancellationToken);

    public Task<TaskRecord> AssembleEpisodeAsync(
        string episodeId, CancellationToken cancellationToken = default) =>
        SendAsync<TaskRecord>(HttpMethod.Post,
            $"api/v1/episodes/{Uri.EscapeDataString(episodeId)}/assemble",
            null, "episodes.assemble", null, cancellationToken);

    public Task<PreviewContent> GetThumbnailAsync(
        string taskId, string thumbnailId, CancellationToken cancellationToken = default) =>
        SendAsync<PreviewContent>(HttpMethod.Get,
            $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/thumbnails/{Uri.EscapeDataString(thumbnailId)}",
            null, "artifacts.thumbnail", null, cancellationToken);


    /// <summary>Studio 一次点击：领取 Mac 上已审核的待传首帧并在 Windows 本机核验，绝不触发生成。</summary>
    public async Task<FrameStagingReceipt?> ClaimAndStagePendingFramesAsync(
        string workerRoot,
        CancellationToken cancellationToken = default)
    {
        var http = _frameTransferClient ?? _httpClient;
        var baseUri = http.BaseAddress
            ?? throw new InvalidOperationException("FRAME_TRANSFER_BASE_URI_MISSING");
        var local = string.Equals(baseUri.Host, "localhost", StringComparison.OrdinalIgnoreCase) ||
            (IPAddress.TryParse(baseUri.Host, out var address) && IPAddress.IsLoopback(address));
        if ((baseUri.Scheme != Uri.UriSchemeHttps &&
             !(baseUri.Scheme == Uri.UriSchemeHttp && local)) ||
            !string.IsNullOrEmpty(baseUri.UserInfo))
        {
            throw new InvalidDataException("FRAME_TRANSFER_SECURE_INPUT_REQUIRED");
        }
        if (!Directory.Exists(workerRoot))
        {
            throw new InvalidDataException("FRAME_TRANSFER_WORKER_PROJECT_MISSING");
        }

        // 只通过现有设备 Bearer 向 Mac 领取主人已经批准的资料，绝不接触 Owner Token。
        using var request = new HttpRequestMessage(
            HttpMethod.Post, "api/v1/studio/frame-transfer/claim");
        using var response = await http.SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.NoContent)
        {
            return null;
        }
        if (response.StatusCode != HttpStatusCode.OK)
        {
            throw new InvalidDataException("FRAME_TRANSFER_CLAIM_NOT_AUTHORIZED_OR_STALE");
        }
        await using var responseStream = await response.Content.ReadAsStreamAsync(
            cancellationToken).ConfigureAwait(false);
        using var body = await JsonDocument.ParseAsync(
            responseStream, cancellationToken: cancellationToken).ConfigureAwait(false);
        var json = body.RootElement;
        if (json.ValueKind != JsonValueKind.Object ||
            json.GetProperty("status").GetString() != "FRAME_TRANSFER_CLAIMED_DATA_ONLY" ||
            json.GetProperty("can_queue").GetBoolean() ||
            json.GetProperty("gpu_authorized").GetBoolean())
        {
            throw new InvalidDataException("FRAME_TRANSFER_CLAIM_INVALID");
        }
        var ticket = json.GetProperty("ticket").GetString() ?? "";
        var manifest = json.GetProperty("source_bindings_sha256").GetString() ?? "";
        var zipSha = json.GetProperty("bundle_sha256").GetString() ?? "";
        // 下载后二次校验，旧 Ticket 不可重新领取，也不生成任何生产 Task。
        return await DownloadAndStageFramesAsync(
            ticket, manifest, zipSha, workerRoot, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>从已由 Mac Owner 签发的一次性凭据下载 ZIP，并使用 .NET 原生代码在 Worker 目录验 SHA。</summary>
    /// <remarks>这只是数据同步；方法绝不创建生产任务、解除 GPU HOLD 或声明 MASTER 已批准。</remarks>
    public async Task<FrameStagingReceipt> DownloadAndStageFramesAsync(
        string transferTicket,
        string expectedManifestSha256,
        string expectedBundleSha256,
        string workerRoot,
        CancellationToken cancellationToken = default)
    {
        var http = _frameTransferClient ?? _httpClient;
        var baseUri = http.BaseAddress
            ?? throw new InvalidOperationException("FRAME_TRANSFER_BASE_URI_MISSING");
        var host = baseUri.Host;
        var local = string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase) ||
            (IPAddress.TryParse(host, out var address) && IPAddress.IsLoopback(address));
        if ((baseUri.Scheme != Uri.UriSchemeHttps && !(baseUri.Scheme == Uri.UriSchemeHttp && local)) ||
            !string.IsNullOrEmpty(baseUri.UserInfo) ||
            string.IsNullOrWhiteSpace(transferTicket) ||
            transferTicket.Length is < 20 or > 160 ||
            transferTicket.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '-' or '_')) ||
            !IsLowerSha(expectedManifestSha256) ||
            !IsLowerSha(expectedBundleSha256))
        {
            throw new InvalidDataException("FRAME_TRANSFER_SECURE_INPUT_REQUIRED");
        }

        var temp = Path.Combine(Path.GetTempPath(), $"picotoo-private-frame-{Guid.NewGuid():N}.zip");
        try
        {
            // 只用设备 Bearer + Owner 单次 Ticket；绝不把 Owner Token 放到 Windows。
            using var request = new HttpRequestMessage(
                HttpMethod.Get, "api/v1/studio/frame-transfer/download");
            request.Headers.TryAddWithoutValidation("X-Picotoo-Transfer-Ticket", transferTicket);
            request.Headers.Accept.Clear();
            request.Headers.Accept.ParseAdd("application/zip");
            using var response = await http.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
                .ConfigureAwait(false);
            if (response.StatusCode != HttpStatusCode.OK ||
                response.Content.Headers.ContentType?.MediaType != "application/zip" ||
                !HeaderSha(response, "X-Picotoo-Source-Bindings-Sha256", expectedManifestSha256) ||
                !HeaderSha(response, "X-Picotoo-Bundle-Sha256", expectedBundleSha256))
            {
                throw new InvalidDataException("FRAME_TRANSFER_RESPONSE_NOT_TRUSTED");
            }

            // 逐块下载并在 ZIP 解析之前核对 Mac 提供的原始 bundle SHA。
            using var bundleHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            long total = 0;
            await using (var source = await response.Content.ReadAsStreamAsync(
                cancellationToken).ConfigureAwait(false))
            await using (var file = new FileStream(
                temp, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                1024 * 1024, FileOptions.Asynchronous))
            {
                var buffer = new byte[1024 * 1024];
                int count;
                while ((count = await source.ReadAsync(buffer, cancellationToken)
                    .ConfigureAwait(false)) > 0)
                {
                    total += count;
                    if (total > 129L * 1024 * 1024)
                    {
                        throw new InvalidDataException("FRAME_TRANSFER_SIZE_LIMIT");
                    }
                    bundleHash.AppendData(buffer, 0, count);
                    await file.WriteAsync(buffer.AsMemory(0, count), cancellationToken)
                        .ConfigureAwait(false);
                }
                await file.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            if (total == 0 || !string.Equals(
                Convert.ToHexString(bundleHash.GetHashAndReset()), expectedBundleSha256,
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("FRAME_TRANSFER_BUNDLE_SHA_MISMATCH");
            }

            // Windows 实际重读本地图片字节；即使数据对账成功也不签发 GPU 权限。
            return await FrameBundleStager.StageAsync(
                temp, expectedManifestSha256, workerRoot, cancellationToken)
                .ConfigureAwait(false);
        }
        finally
        {
            File.Delete(temp);
        }
    }

    private static bool IsLowerSha(string value) =>
        value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static bool HeaderSha(HttpResponseMessage response, string name, string expected) =>
        response.Headers.TryGetValues(name, out var values) &&
        values.SequenceEqual(new[] { expected }, StringComparer.Ordinal);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUri,
        object? payload,
        string operation,
        string? idempotencyKey,
        CancellationToken cancellationToken)
    {
        var traceId = Guid.NewGuid().ToString("N");
        using var request = new HttpRequestMessage(method, relativeUri);
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);
        if (!string.IsNullOrWhiteSpace(idempotencyKey))
        {
            request.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
        }
        if (payload is not null)
        {
            request.Content = JsonContent.Create(payload, options: JsonOptions);
        }

        var started = Stopwatch.GetTimestamp();
        var measurementRecorded = false;
        try
        {
            using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken).ConfigureAwait(false);
            var responseTrace = response.Headers.TryGetValues("X-Picotoo-Trace-Id", out var traceValues)
                ? traceValues.FirstOrDefault() ?? traceId
                : traceId;
            RecordMeasurement(operation, started, responseTrace, (int)response.StatusCode);
            measurementRecorded = true;

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

            try
            {
                await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
                    .ConfigureAwait(false);
                var result = await JsonSerializer.DeserializeAsync<T>(
                    stream,
                    JsonOptions,
                    cancellationToken).ConfigureAwait(false);
                return result ?? throw new ApiException(
                    "EMPTY_RESPONSE",
                    "Mac Core 返回了空响应。",
                    retryable: true,
                    responseTrace,
                    (int)response.StatusCode);
            }
            catch (JsonException exception)
            {
                throw new ApiException(
                    "INVALID_RESPONSE",
                    "Mac Core 返回了无法解析的响应。",
                    retryable: true,
                    responseTrace,
                    (int)response.StatusCode,
                    exception);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            if (!measurementRecorded)
            {
                RecordMeasurement(operation, started, traceId, statusCode: 0);
            }
            throw;
        }
        catch (OperationCanceledException exception)
        {
            if (!measurementRecorded)
            {
                RecordMeasurement(operation, started, traceId, statusCode: 0);
            }
            throw new ApiException(
                "NETWORK_TIMEOUT",
                "连接 Mac Core 超时，请检查局域网和服务状态。",
                retryable: true,
                traceId,
                statusCode: 0,
                exception);
        }
        catch (HttpRequestException exception)
        {
            if (!measurementRecorded)
            {
                RecordMeasurement(operation, started, traceId, exception.StatusCode is null
                    ? 0
                    : (int)exception.StatusCode.Value);
            }
            throw new ApiException(
                "NETWORK_ERROR",
                "无法连接 Mac Core，请检查地址、网络和防火墙。",
                retryable: true,
                traceId,
                exception.StatusCode is null ? 0 : (int)exception.StatusCode.Value,
                exception);
        }
    }

    private static async Task<ApiErrorDetail?> ReadErrorAsync(
        HttpContent content,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = await content.ReadAsStreamAsync(cancellationToken)
                .ConfigureAwait(false);
            var envelope = await JsonSerializer.DeserializeAsync<ApiErrorEnvelope>(
                stream,
                JsonOptions,
                cancellationToken).ConfigureAwait(false);
            return envelope?.Error;
        }
        catch (JsonException)
        {
            // 非 JSON 错误页仍由 HTTP 状态和 Trace ID 形成可定位异常。
            return null;
        }
    }

    private void RecordMeasurement(
        string operation,
        long started,
        string traceId,
        int statusCode)
    {
        var elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        RequestMeasured?.Invoke(
            this,
            new RequestMeasurement(operation, elapsed, traceId, statusCode));
    }

    private static bool IsRetryableStatus(HttpStatusCode statusCode) =>
        statusCode is HttpStatusCode.RequestTimeout
            or HttpStatusCode.TooManyRequests
            or HttpStatusCode.BadGateway
            or HttpStatusCode.ServiceUnavailable
            or HttpStatusCode.GatewayTimeout;

    private static void ConfigureHeaders(HttpClient client, string token)
    {
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        client.DefaultRequestHeaders.Accept.Clear();
        client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Desktop/2.2-phase2");
    }

    private static Uri EnsureTrailingSlash(Uri baseUri)
    {
        var text = baseUri.AbsoluteUri.EndsWith('/')
            ? baseUri.AbsoluteUri
            : baseUri.AbsoluteUri + "/";
        return new Uri(text, UriKind.Absolute);
    }

    /// <summary>仅在客户端拥有连接池时释放底层资源。</summary>
    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _frameTransferClient?.Dispose();
            _httpClient.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}
