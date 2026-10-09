using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>C008A2 CaptionOverlayPlan 的只读来源抽象。</summary>
public interface ICaptionOverlayPlanGateway
{
    Task<CaptionOverlayPlanResponseRecord> GetCaptionOverlayPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken);
}

/// <summary>
/// GET /api/v1/postproduction/production/{id}/caption-overlay-plan 的窄客户端：保留 Trace ID，
/// 响应有界，严格 JSON，类型化有界错误；从不记录文案或原始响应。
/// </summary>
public sealed partial class MacCoreCaptionOverlayClient : ICaptionOverlayPlanGateway, IAsyncDisposable
{
    public const int MaxResponseBytes = 1024 * 1024;
    private const int MaxErrorBytes = 16 * 1024;

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    [GeneratedRegex("^[A-Z0-9_]{1,80}$")]
    private static partial Regex ErrorCodePattern();

    public MacCoreCaptionOverlayClient(HttpClient client, string token)
        : this(client, token, ownsClient: false)
    {
    }

    private MacCoreCaptionOverlayClient(HttpClient client, string token, bool ownsClient)
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
    }

    public static MacCoreCaptionOverlayClient Create(MacCoreClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            ConnectTimeout = options.ConnectTimeout,
            MaxConnectionsPerServer = 2,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = options.BaseUri.AbsoluteUri.EndsWith('/')
                ? options.BaseUri
                : new Uri(options.BaseUri.AbsoluteUri + "/", UriKind.Absolute),
            Timeout = options.RequestTimeout,
        };
        return new MacCoreCaptionOverlayClient(client, options.Token, ownsClient: true);
    }

    public async Task<CaptionOverlayPlanResponseRecord> GetCaptionOverlayPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(productionJobId))
        {
            throw new ArgumentException("Production identity 不能为空。", nameof(productionJobId));
        }
        var traceId = Guid.NewGuid().ToString("N");
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            $"api/v1/postproduction/production/{Uri.EscapeDataString(productionJobId)}/caption-overlay-plan");
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);
        using var response = await _client.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw await BuildErrorAsync(response, traceId, cancellationToken).ConfigureAwait(false);
        }

        var bytes = await ReadBoundedAsync(response, MaxResponseBytes, cancellationToken).ConfigureAwait(false)
            ?? throw new ApiException(
                "CAPTION_OVERLAY_RESPONSE_TOO_LARGE",
                "CaptionOverlayPlan 响应超过安全上限。",
                false,
                traceId,
                (int)response.StatusCode);
        var parsed = CaptionOverlayPlanParser.Parse(bytes);
        if (!string.Equals(parsed.Plan.ProductionJobId, productionJobId, StringComparison.Ordinal))
        {
            throw new TextOverlayException(TextOverlayException.PlanInvalid);
        }
        return parsed;
    }

    private static async Task<byte[]?> ReadBoundedAsync(
        HttpResponseMessage response,
        int limit,
        CancellationToken cancellationToken)
    {
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var bounded = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                return bounded.ToArray();
            }
            if (bounded.Length + read > limit)
            {
                return null;
            }
            bounded.Write(buffer, 0, read);
        }
    }

    /// <summary>只提取形如 [A-Z0-9_] 的服务端错误码；响应正文的其余部分一律丢弃。</summary>
    private static async Task<ApiException> BuildErrorAsync(
        HttpResponseMessage response,
        string traceId,
        CancellationToken cancellationToken)
    {
        var code = "CAPTION_OVERLAY_HTTP_ERROR";
        try
        {
            var body = await ReadBoundedAsync(response, MaxErrorBytes, cancellationToken).ConfigureAwait(false);
            if (body is not null)
            {
                using var document = JsonDocument.Parse(body);
                if (document.RootElement.TryGetProperty("error", out var error)
                    && error.TryGetProperty("code", out var codeElement)
                    && codeElement.ValueKind == JsonValueKind.String
                    && codeElement.GetString() is { } candidate
                    && ErrorCodePattern().IsMatch(candidate))
                {
                    code = candidate;
                }
            }
        }
        catch (JsonException)
        {
            // 非 JSON 错误正文被忽略。
        }
        var status = response.StatusCode;
        return new ApiException(
            code,
            $"Mac Core 文字叠加计划返回 HTTP {(int)status}。",
            status is HttpStatusCode.RequestTimeout
                or HttpStatusCode.TooManyRequests
                or HttpStatusCode.BadGateway
                or HttpStatusCode.ServiceUnavailable
                or HttpStatusCode.GatewayTimeout
                || code == "TEXT_PRESENTATION_NOT_READY",
            traceId,
            (int)status);
    }

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _client.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}
