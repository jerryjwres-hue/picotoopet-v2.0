using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>25.1 Promotion 客户端；仅传递不可变身份、exact digest 与闭合决定。</summary>
public sealed class MacCoreQualityPromotionClient : IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 2 * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreQualityPromotionClient(HttpClient client, string token)
        : this(client, token, ownsClient: false)
    {
    }

    private MacCoreQualityPromotionClient(HttpClient client, string token, bool ownsClient)
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
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-Promotion/2.3.25.1");
    }

    public static MacCoreQualityPromotionClient Create(MacCoreClientOptions options)
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
        return new MacCoreQualityPromotionClient(client, options.Token, ownsClient: true);
    }

    public Task<QualityPromotionRecord> CreateAsync(
        QualityPromotionCreateRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionRecord>(HttpMethod.Post, "api/v1/deep-ai/promotions", payload, cancellationToken);

    public Task<QualityPromotionRecord[]> GetPromotionsAsync(
        string? projectKey = null,
        string? candidateClass = null,
        CancellationToken cancellationToken = default)
    {
        var query = new List<string> { "limit=200" };
        if (!string.IsNullOrWhiteSpace(projectKey))
        {
            query.Add($"project_key={Escape(projectKey)}");
        }
        if (!string.IsNullOrWhiteSpace(candidateClass))
        {
            query.Add($"candidate_class={Escape(candidateClass)}");
        }
        return SendJsonAsync<QualityPromotionRecord[]>(
            HttpMethod.Get,
            $"api/v1/deep-ai/promotions?{string.Join("&", query)}",
            null,
            cancellationToken);
    }

    public Task<QualityPromotionRecord> GetPromotionAsync(
        string promotionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}",
            null,
            cancellationToken);

    public Task<QualityPromotionRecord> ReconcileAsync(
        string promotionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/reconcile",
            new { },
            cancellationToken);

    public Task<QualityPromotionApprovalRequestRecord> GetActivationRequestAsync(
        string promotionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionApprovalRequestRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/activation-request",
            null,
            cancellationToken);

    public Task<QualityPromotionRecord> DecideActivationAsync(
        string promotionId,
        QualityPromotionDecisionRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/activation-decision",
            payload,
            cancellationToken);

    public Task<QualityPromotionApprovalRequestRecord> RequestRollbackAsync(
        string promotionId,
        QualityPromotionRollbackRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionApprovalRequestRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/rollback-request",
            payload,
            cancellationToken);

    public Task<QualityPromotionApprovalRequestRecord> GetRollbackRequestAsync(
        string promotionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionApprovalRequestRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/rollback-request",
            null,
            cancellationToken);

    public Task<QualityPromotionRecord> DecideRollbackAsync(
        string promotionId,
        QualityPromotionDecisionRequest payload,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionRecord>(
            HttpMethod.Post,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/rollback-decision",
            payload,
            cancellationToken);

    public Task<QualityPromotionHistoryRecord> GetHistoryAsync(
        string promotionId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<QualityPromotionHistoryRecord>(
            HttpMethod.Get,
            $"api/v1/deep-ai/promotions/{Escape(promotionId)}/history",
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
        return result ?? throw new InvalidDataException("Promotion response body was empty.");
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
                    "QUALITY_PROMOTION_RESPONSE_TOO_LARGE",
                    "Promotion 响应超过安全上限。",
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
            "QUALITY_PROMOTION_HTTP_ERROR",
            $"Mac Core Promotion 返回 HTTP {(int)statusCode}。",
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
            throw new ArgumentException("Promotion identity 不能为空。", nameof(value));
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
