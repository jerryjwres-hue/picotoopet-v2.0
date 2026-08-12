using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>2.3.22.1 Deep-AI 用户控制面；只发送 source identity、reconcile 和 bounded feedback。</summary>
public sealed class MacCoreDeepAiClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 2 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreDeepAiClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreDeepAiClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    public static MacCoreDeepAiClient Create(MacCoreClientOptions options)
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
        return new MacCoreDeepAiClient(client, options.Token, ownsClient: true);
    }

    public Task<DeepAiEscalationRecord> PrepareAsync(
        DeepAiEscalationPrepareRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiEscalationRecord>(
            HttpMethod.Post,
            "api/v1/deep-ai/escalations",
            payload,
            cancellationToken);

    public Task<DeepAiEscalationRecord[]> GetEscalationsAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiEscalationRecord[]>(
            HttpMethod.Get,
            "api/v1/deep-ai/escalations?limit=200",
            null,
            cancellationToken);

    public Task<DeepAiEscalationRecord> GetEscalationAsync(
        string escalationJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiEscalationRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/escalations/{Escape(escalationJobId)}",
            null,
            cancellationToken);

    public Task<DeepAiEscalationRecord> ReconcileAsync(
        string escalationJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiEscalationRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/escalations/{Escape(escalationJobId)}/reconcile",
            new { },
            cancellationToken);

    public Task<DeepAiReadinessRecord> GetReadinessAsync(
        string escalationJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiReadinessRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/escalations/{Escape(escalationJobId)}/readiness",
            null,
            cancellationToken);

    public Task<DeepAiUsageRecord> GetUsageAsync(
        string escalationJobId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiUsageRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/escalations/{Escape(escalationJobId)}/usage",
            null,
            cancellationToken);

    public Task<DeepAiLearningObservationRecord> RecordFeedbackAsync(
        string escalationJobId,
        DeepAiFeedbackRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<DeepAiLearningObservationRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/escalations/{Escape(escalationJobId)}/feedback",
            payload,
            cancellationToken);

    public Task<DeepAiLearningEventRecord[]> GetLearningAsync(
        string? projectKey = null,
        CancellationToken cancellationToken = default)
    {
        var path = string.IsNullOrWhiteSpace(projectKey)
            ? "api/v1/deep-ai/learning?limit=200"
            : $"api/v1/deep-ai/learning?project_key={Uri.EscapeDataString(projectKey)}&limit=200";
        return SendJsonAsync<DeepAiLearningEventRecord[]>(
            HttpMethod.Get,
            path,
            null,
            cancellationToken);
    }

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
        return result ?? throw new InvalidDataException("Deep-AI response body was empty.");
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
                    "DEEP_AI_RESPONSE_TOO_LARGE",
                    "Deep-AI 响应超过安全上限。",
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
            "DEEP_AI_HTTP_ERROR",
            $"Mac Core Deep-AI 返回 HTTP {(int)statusCode}。",
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
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-DeepAI/2.3.22.1");
    }

    private static string Escape(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("Deep-AI identity 不能为空。", nameof(value));
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
