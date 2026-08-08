using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>项目、工作流、健康与结构化诊断的有界 REST 客户端。</summary>
public sealed class MacCoreAutomationClient : IAsyncDisposable
{
    private const int MaxResponseBytes = 512 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public MacCoreAutomationClient(HttpClient client, string token)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _ownsClient = false;
        ConfigureHeaders(token);
    }

    private MacCoreAutomationClient(HttpClient client, string token, bool ownsClient)
    {
        _client = client;
        _ownsClient = ownsClient;
        ConfigureHeaders(token);
    }

    public static MacCoreAutomationClient Create(MacCoreClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            ConnectTimeout = options.ConnectTimeout,
            MaxConnectionsPerServer = 8,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        };
        var client = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = EnsureTrailingSlash(options.BaseUri),
            Timeout = options.RequestTimeout,
        };
        return new MacCoreAutomationClient(client, options.Token, ownsClient: true);
    }

    public Task<ProjectRecord[]> GetProjectsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<ProjectRecord[]>(HttpMethod.Get, "api/v1/projects", null, null, cancellationToken);

    public Task<ProjectRecord> CreateProjectAsync(
        ProjectCreateRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProjectRecord>(HttpMethod.Post, "api/v1/projects", request, null, cancellationToken);

    public Task<ProjectRecord> ArchiveProjectAsync(
        string projectId,
        CancellationToken cancellationToken = default) =>
        SendAsync<ProjectRecord>(
            HttpMethod.Post,
            $"api/v1/projects/{Uri.EscapeDataString(projectId)}/archive",
            null,
            null,
            cancellationToken);

    public Task<WorkflowRecord[]> GetWorkflowsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<WorkflowRecord[]>(HttpMethod.Get, "api/v1/workflows?limit=200", null, null, cancellationToken);

    public Task<WorkflowRecord> CreateWorkflowAsync(
        WorkflowCreateRequest request,
        CancellationToken cancellationToken = default) =>
        SendAsync<WorkflowRecord>(HttpMethod.Post, "api/v1/workflows", request, request.IdempotencyKey, cancellationToken);

    public Task<WorkflowRecord> ReconcileWorkflowAsync(string workflowId, CancellationToken cancellationToken = default) =>
        WorkflowActionAsync(workflowId, "reconcile", cancellationToken);

    public Task<WorkflowRecord> PauseWorkflowAsync(string workflowId, CancellationToken cancellationToken = default) =>
        WorkflowActionAsync(workflowId, "pause", cancellationToken);

    public Task<WorkflowRecord> ResumeWorkflowAsync(string workflowId, CancellationToken cancellationToken = default) =>
        WorkflowActionAsync(workflowId, "resume", cancellationToken);

    public Task<WorkflowRecord> CancelWorkflowAsync(string workflowId, CancellationToken cancellationToken = default) =>
        WorkflowActionAsync(workflowId, "cancel", cancellationToken);

    public Task<AutomationHealthResponse> GetAutomationHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<AutomationHealthResponse>(HttpMethod.Get, "api/v1/automation/health", null, null, cancellationToken);

    public Task<AutomationDiagnosticsResponse> GetAutomationDiagnosticsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<AutomationDiagnosticsResponse>(HttpMethod.Get, "api/v1/automation/diagnostics?limit=100", null, null, cancellationToken);

    private Task<WorkflowRecord> WorkflowActionAsync(
        string workflowId,
        string action,
        CancellationToken cancellationToken) =>
        SendAsync<WorkflowRecord>(
            HttpMethod.Post,
            $"api/v1/workflows/{Uri.EscapeDataString(workflowId)}/{action}",
            null,
            null,
            cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string relativeUri,
        object? payload,
        string? idempotencyKey,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, relativeUri);
        var traceId = Guid.NewGuid().ToString("N");
        request.Headers.TryAddWithoutValidation("X-Picotoo-Trace-Id", traceId);
        if (!string.IsNullOrWhiteSpace(idempotencyKey))
        {
            request.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
        }
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
            throw new ApiException(
                "AUTOMATION_HTTP_ERROR",
                $"Mac Core 返回 HTTP {(int)response.StatusCode}。",
                response.StatusCode is HttpStatusCode.RequestTimeout
                    or HttpStatusCode.TooManyRequests
                    or HttpStatusCode.BadGateway
                    or HttpStatusCode.ServiceUnavailable
                    or HttpStatusCode.GatewayTimeout,
                traceId,
                (int)response.StatusCode);
        }

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var bounded = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (bounded.Length + read > MaxResponseBytes)
            {
                throw new ApiException(
                    "AUTOMATION_RESPONSE_TOO_LARGE",
                    "Mac Core 自动化响应超过安全上限。",
                    false,
                    traceId,
                    (int)response.StatusCode);
            }
            bounded.Write(buffer, 0, read);
        }
        bounded.Position = 0;
        var result = await JsonSerializer.DeserializeAsync<T>(bounded, JsonOptions, cancellationToken)
            .ConfigureAwait(false);
        return result ?? throw new ApiException(
            "AUTOMATION_RESPONSE_INVALID",
            "Mac Core 自动化响应为空或无法解析。",
            false,
            traceId,
            (int)response.StatusCode);
    }

    private void ConfigureHeaders(string token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }
        _client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        _client.DefaultRequestHeaders.Accept.Clear();
        _client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("PicotooPet-Windows-ControlCenter/2.3");
    }

    private static Uri EnsureTrailingSlash(Uri uri) =>
        uri.AbsoluteUri.EndsWith('/')
            ? uri
            : new Uri(uri.AbsoluteUri + "/", UriKind.Absolute);

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _client.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}
