using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>
/// 只承载任务可恢复隐藏/恢复和 Research 固定结果读取。
/// 不接受任意 URL、文件路径或执行命令。
/// </summary>
public sealed class TaskLifecycleClient : IAsyncDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;

    public TaskLifecycleClient(MacCoreClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            ConnectTimeout = options.ConnectTimeout,
            MaxConnectionsPerServer = 8,
        };
        _client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = EnsureTrailingSlash(options.BaseUri),
            Timeout = options.RequestTimeout,
        };
        _client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", options.Token);
        _client.DefaultRequestHeaders.Accept.Add(
            new MediaTypeWithQualityHeaderValue("application/json"));
    }

    public Task<TaskVisibilityBatchResponse> HideTasksAsync(
        IReadOnlyList<string> taskIds,
        CancellationToken cancellationToken = default) =>
        PostAsync<TaskVisibilityBatchResponse>(
            "api/v1/tasks/batch-hide",
            new TaskIdBatchRequest(taskIds),
            cancellationToken);

    public Task<TaskVisibilityBatchResponse> RestoreTasksAsync(
        IReadOnlyList<string> taskIds,
        CancellationToken cancellationToken = default) =>
        PostAsync<TaskVisibilityBatchResponse>(
            "api/v1/tasks/batch-restore",
            new TaskIdBatchRequest(taskIds),
            cancellationToken);

    public async Task<TaskVisibilityOutcome> HideTaskAsync(
        string taskId,
        CancellationToken cancellationToken = default)
    {
        using var response = await _client.PostAsync(
            $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/hide",
            content: null,
            cancellationToken).ConfigureAwait(false);
        return await ReadAsync<TaskVisibilityOutcome>(response, cancellationToken)
            .ConfigureAwait(false);
    }

    public Task<ResearchSearchResult> GetResearchResultAsync(
        string taskId,
        CancellationToken cancellationToken = default) =>
        GetAsync<ResearchSearchResult>(
            $"api/v1/tasks/{Uri.EscapeDataString(taskId)}/research-result",
            cancellationToken);

    private async Task<T> GetAsync<T>(
        string relativeUri,
        CancellationToken cancellationToken)
    {
        using var response = await _client.GetAsync(relativeUri, cancellationToken)
            .ConfigureAwait(false);
        return await ReadAsync<T>(response, cancellationToken).ConfigureAwait(false);
    }

    private async Task<T> PostAsync<T>(
        string relativeUri,
        object payload,
        CancellationToken cancellationToken)
    {
        using var response = await _client.PostAsJsonAsync(
            relativeUri,
            payload,
            JsonOptions,
            cancellationToken).ConfigureAwait(false);
        return await ReadAsync<T>(response, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<T> ReadAsync<T>(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException(
                $"Mac Core task lifecycle HTTP {(int)response.StatusCode}.",
                inner: null,
                response.StatusCode);
        }
        var value = await response.Content.ReadFromJsonAsync<T>(
            JsonOptions,
            cancellationToken).ConfigureAwait(false);
        return value ?? throw new InvalidDataException("Mac Core 返回空 JSON。 ");
    }

    private static Uri EnsureTrailingSlash(Uri value) =>
        value.AbsoluteUri.EndsWith('/', StringComparison.Ordinal)
            ? value
            : new Uri(value.AbsoluteUri + "/", UriKind.Absolute);

    public ValueTask DisposeAsync()
    {
        _client.Dispose();
        return ValueTask.CompletedTask;
    }
}
