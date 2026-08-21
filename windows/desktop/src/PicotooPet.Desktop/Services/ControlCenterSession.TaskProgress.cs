using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>任务详情使用的只读耐久进度通道；来源仍是同一个 Mac Core REST 真相层。</summary>
public sealed partial class ControlCenterSession
{
    private const int MaxTaskProgressResponseBytes = 512 * 1024;

    private static readonly JsonSerializerOptions TaskProgressJsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private static readonly HttpClient TaskProgressHttpClient = CreateTaskProgressHttpClient();

    /// <summary>读取 Core 已持久化的真实进度；Windows 不根据耗时推算阶段或百分比。</summary>
    public async Task<TaskProgressSnapshot> GetTaskProgressAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);

        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }

        var token = _tokenStore.Read();
        ValidateConnectionInput(macBaseUrl, token ?? string.Empty, out var baseUri);
        var normalizedBaseUri = baseUri.AbsoluteUri.EndsWith("/", StringComparison.Ordinal)
            ? baseUri
            : new Uri(baseUri.AbsoluteUri + "/", UriKind.Absolute);
        var relativePath = $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/progress";
        var requestUri = new Uri(normalizedBaseUri, relativePath);
        var traceId = Guid.NewGuid().ToString("N");

        using var request = new HttpRequestMessage(HttpMethod.Get, requestUri);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);

        using var response = await TaskProgressHttpClient.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();

        var payload = await ReadTaskProgressResponseAsync(
            response.Content,
            cancellationToken).ConfigureAwait(false);
        return JsonSerializer.Deserialize<TaskProgressSnapshot>(payload, TaskProgressJsonOptions)
            ?? throw new InvalidDataException("Mac Core 返回了空任务进度响应。");
    }

    private static HttpClient CreateTaskProgressHttpClient()
    {
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime    = TimeSpan.FromMinutes(5),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout              = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer     = 8,
            AutomaticDecompression      = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        return new HttpClient(handler, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
    }

    private static async Task<byte[]> ReadTaskProgressResponseAsync(
        HttpContent content,
        CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is long contentLength
            && contentLength > MaxTaskProgressResponseBytes)
        {
            throw new InvalidDataException("Mac Core 任务进度响应超过安全读取上限。");
        }

        await using var stream = await content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var buffer = new MemoryStream(capacity: 16 * 1024);
        var block = new byte[8 * 1024];
        var total = 0;
        while (true)
        {
            var read = await stream.ReadAsync(block.AsMemory(), cancellationToken)
                .ConfigureAwait(false);
            if (read == 0)
            {
                return buffer.ToArray();
            }

            total = checked(total + read);
            if (total > MaxTaskProgressResponseBytes)
            {
                throw new InvalidDataException("Mac Core 任务进度响应超过安全读取上限。");
            }
            await buffer.WriteAsync(block.AsMemory(0, read), cancellationToken)
                .ConfigureAwait(false);
        }
    }
}
