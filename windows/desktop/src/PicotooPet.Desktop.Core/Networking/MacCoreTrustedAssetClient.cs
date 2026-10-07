using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>受信资产注册的最小抽象；只传有界事实，不传源路径或字节。</summary>
public interface ITrustedAssetRegistrar
{
    Task<TrustedAssetRecord> RegisterAsync(
        TrustedAssetRegisterRequest request,
        CancellationToken cancellationToken);
}

/// <summary>Mac Core /api/v1/assets 窄客户端；无上传、无任意路径输入。</summary>
public sealed class MacCoreTrustedAssetClient : ITrustedAssetRegistrar, IAsyncDisposable
{
    private const int MaxJsonResponseBytes = 64 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreTrustedAssetClient(HttpClient client, string token)
        : this(client, token, ownsClient: false)
    {
    }

    private MacCoreTrustedAssetClient(HttpClient client, string token, bool ownsClient)
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

    /// <summary>从现有配对信息创建；调用方负责释放。</summary>
    public static MacCoreTrustedAssetClient Create(MacCoreClientOptions options)
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
        return new MacCoreTrustedAssetClient(client, options.Token, ownsClient: true);
    }

    public async Task<TrustedAssetRecord> RegisterAsync(
        TrustedAssetRegisterRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        using var message = new HttpRequestMessage(HttpMethod.Post, "api/v1/assets")
        {
            Content = JsonContent.Create(request, options: JsonOptions),
        };
        message.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", Guid.NewGuid().ToString("N"));
        using var response = await _client.SendAsync(
            message,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new ApiException(
                "TRUSTED_ASSET_HTTP_ERROR",
                $"Mac Core 资产登记返回 HTTP {(int)response.StatusCode}。",
                response.StatusCode is HttpStatusCode.RequestTimeout
                    or HttpStatusCode.TooManyRequests
                    or HttpStatusCode.BadGateway
                    or HttpStatusCode.ServiceUnavailable
                    or HttpStatusCode.GatewayTimeout,
                null,
                (int)response.StatusCode);
        }

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var bounded = new MemoryStream();
        var buffer = new byte[8 * 1024];
        while (true)
        {
            var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (bounded.Length + read > MaxJsonResponseBytes)
            {
                throw new ApiException(
                    "TRUSTED_ASSET_RESPONSE_TOO_LARGE",
                    "资产登记响应超过安全上限。",
                    false,
                    null,
                    0);
            }
            bounded.Write(buffer, 0, read);
        }
        bounded.Position = 0;
        var record = await JsonSerializer.DeserializeAsync<TrustedAssetRecord>(
            bounded,
            JsonOptions,
            cancellationToken).ConfigureAwait(false);
        return record ?? throw new ApiException(
            "TRUSTED_ASSET_RESPONSE_INVALID",
            "资产登记响应无效。",
            false,
            null,
            0);
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
