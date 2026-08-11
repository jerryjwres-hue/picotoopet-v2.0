using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>只允许连接固定本机 ComfyUI API；不接受 UI/Core 传入 endpoint。</summary>
public sealed class ComfyProductionClient : IAsyncDisposable
{
    public static readonly Uri FixedBaseAddress = new("http://127.0.0.1:8188/", UriKind.Absolute);
    private const int MaxJsonBytes = 8 * 1024 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public ComfyProductionClient(HttpClient client)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ValidateBaseAddress(_client.BaseAddress);
    }

    private ComfyProductionClient(HttpClient client, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ValidateBaseAddress(_client.BaseAddress);
    }

    /// <summary>创建固定 127.0.0.1:8188 客户端；没有外部 endpoint 参数。</summary>
    public static ComfyProductionClient Create()
    {
        var handler = new SocketsHttpHandler
        {
            ConnectTimeout = TimeSpan.FromSeconds(4),
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            MaxConnectionsPerServer = 2,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = FixedBaseAddress,
            Timeout = TimeSpan.FromMinutes(20),
        };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-ComfyProduction/2.3");
        return new ComfyProductionClient(client, ownsClient: true);
    }

    /// <summary>读取本地 object_info，供 preflight 验证 native node 是否存在。</summary>
    public Task<JsonObject> GetObjectInfoAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync(HttpMethod.Get, "object_info", null, cancellationToken);

    /// <summary>向固定 loopback ComfyUI 提交已经过 validator 的 API graph。</summary>
    public async Task<string> SubmitPromptAsync(
        JsonObject prompt,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(prompt);
        var envelope = new JsonObject { ["prompt"] = prompt.DeepClone() };
        var response = await SendJsonAsync(HttpMethod.Post, "prompt", envelope, cancellationToken)
            .ConfigureAwait(false);
        var promptId = response["prompt_id"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(promptId))
        {
            throw new InvalidDataException("COMFY_PROMPT_ID_MISSING");
        }
        return promptId;
    }

    /// <summary>读取单个 prompt 的本地 history；prompt id 只能来自提交响应。</summary>
    public Task<JsonObject> GetHistoryAsync(
        string promptId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(promptId) || promptId.Length > 200)
        {
            throw new ArgumentException("Comfy prompt id 无效。", nameof(promptId));
        }
        return SendJsonAsync(
            HttpMethod.Get,
            $"history/{Uri.EscapeDataString(promptId)}",
            null,
            cancellationToken);
    }

    private async Task<JsonObject> SendJsonAsync(
        HttpMethod method,
        string relativeUri,
        JsonObject? payload,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUri);
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
            throw new HttpRequestException(
                $"COMFY_HTTP_ERROR:{(int)response.StatusCode}",
                inner: null,
                response.StatusCode);
        }
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var bounded = await ReadBoundedAsync(stream, cancellationToken).ConfigureAwait(false);
        var node = await JsonNode.ParseAsync(bounded, cancellationToken: cancellationToken)
            .ConfigureAwait(false);
        return node as JsonObject ?? throw new InvalidDataException("COMFY_JSON_ROOT_INVALID");
    }

    private static async Task<MemoryStream> ReadBoundedAsync(
        Stream stream,
        CancellationToken cancellationToken)
    {
        var memory = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (memory.Length + read > MaxJsonBytes)
            {
                memory.Dispose();
                throw new InvalidDataException("COMFY_RESPONSE_TOO_LARGE");
            }
            memory.Write(buffer, 0, read);
        }
        memory.Position = 0;
        return memory;
    }

    private static void ValidateBaseAddress(Uri? baseAddress)
    {
        if (baseAddress is null
            || !string.Equals(baseAddress.Scheme, Uri.UriSchemeHttp, StringComparison.Ordinal)
            || !string.Equals(baseAddress.Host, "127.0.0.1", StringComparison.Ordinal)
            || baseAddress.Port != 8188
            || baseAddress.AbsolutePath != "/")
        {
            throw new InvalidOperationException("COMFY_ENDPOINT_MUST_BE_LOOPBACK_127_0_0_1_8188");
        }
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
