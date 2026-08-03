using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 REST 初始快照、旧服务降级和序号跳跃恢复。</summary>
internal static class StateSyncCoordinatorSmokeTests
{
    /// <summary>执行同步协调器的确定性内存测试。</summary>
    public static async Task RunAsync()
    {
        await VerifyInitialSnapshotAsync(capabilitiesAvailable: true).ConfigureAwait(false);
        await VerifyInitialSnapshotAsync(capabilitiesAvailable: false).ConfigureAwait(false);
        await VerifyGapTriggersOneBoundedReloadAsync().ConfigureAwait(false);
    }

    private static async Task VerifyInitialSnapshotAsync(bool capabilitiesAvailable)
    {
        using var httpClient = new HttpClient(
            new SnapshotHttpMessageHandler(capabilitiesAvailable))
        {
            BaseAddress = new Uri("http://127.0.0.1:8766/"),
        };
        var client          = new MacCoreClient(httpClient, "fixture-token-0123456789");
        var connectionStore = new ConnectionStateStore();
        var capabilityStore = new CapabilityStateStore();
        var taskStore       = new TaskStateStore();
        await using var coordinator = new StateSyncCoordinator(
            client,
            connectionStore,
            capabilityStore,
            taskStore,
            eventStreamFactory: null);

        var health = await coordinator.InitializeSnapshotAsync(CancellationToken.None)
            .ConfigureAwait(false);

        SmokeAssert.True(health.Status == "ok", "健康快照缺失");
        SmokeAssert.True(taskStore.Snapshot.Tasks.Count == 1, "初始任务快照缺失");
        SmokeAssert.True(
            connectionStore.Snapshot.State == ConnectionState.Online,
            "初始快照完成后连接状态错误");
        SmokeAssert.True(
            capabilityStore.Snapshot.Features.ConnectorContractV1 == capabilitiesAvailable,
            "能力降级结果错误");
        SmokeAssert.True(
            !capabilityStore.Snapshot.Features.Dashboard,
            "未实现 Dashboard 不得自动启用");
    }

    private static async Task VerifyGapTriggersOneBoundedReloadAsync()
    {
        var handler = new SnapshotHttpMessageHandler(capabilitiesAvailable: true);
        using var httpClient = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8766/"),
        };
        var client          = new MacCoreClient(httpClient, "fixture-token-0123456789");
        var connectionStore = new ConnectionStateStore();
        var capabilityStore = new CapabilityStateStore();
        var taskStore       = new TaskStateStore();
        var diagnostics     = new List<string>();
        await using var coordinator = new StateSyncCoordinator(
            client,
            connectionStore,
            capabilityStore,
            taskStore,
            _ => new GapEventStreamSession());
        coordinator.DiagnosticRaised += (_, diagnostic) => diagnostics.Add(diagnostic);

        await coordinator.InitializeSnapshotAsync(CancellationToken.None).ConfigureAwait(false);
        await coordinator.RunEventStreamAsync(CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.True(handler.TasksRequestCount == 2, "序号跳跃必须且只能重载一次任务");
        SmokeAssert.True(taskStore.Snapshot.LastSequence == 3, "恢复后序号未对齐到触发事件");
        SmokeAssert.True(
            diagnostics.Count(value => value.StartsWith("event_sequence_gap:", StringComparison.Ordinal)) == 1,
            "序号跳跃诊断记录数量错误");
    }

    private static EventEnvelope CreateTaskEvent(long sequence)
    {
        var timestamp = new DateTimeOffset(
            year: 2026,
            month: 8,
            day: 1,
            hour: 0,
            minute: 0,
            second: 0,
            offset: TimeSpan.Zero);
        var payload = JsonSerializer.SerializeToElement(new
        {
            task_id = "task-0001",
            parent_task_id = (string?)null,
            project_id = (string?)null,
            task_type = "analysis",
            status = "Running",
            priority = 100,
            resource_tag = (string?)null,
            payload = new { },
            attempt_count = 0,
            max_attempts = 3,
            timeout_seconds = 3600,
            created_at = timestamp,
            updated_at = timestamp,
            error_code = (string?)null,
            error_message = (string?)null,
        });
        return new EventEnvelope(
            "2.3.0",
            sequence,
            $"event-{sequence}",
            "task.updated",
            "trace-gap",
            timestamp,
            payload);
    }

    private sealed class GapEventStreamSession : IEventStreamSession
    {
        public event EventHandler<ConnectionState>? ConnectionStateChanged;
        public event EventHandler<SocketMeasurement>? SocketMeasured;

        public async Task RunAsync(
            Func<EventEnvelope, CancellationToken, ValueTask> consume,
            CancellationToken cancellationToken)
        {
            ConnectionStateChanged?.Invoke(this, ConnectionState.Online);
            SocketMeasured?.Invoke(this, new SocketMeasurement(1, "fixture-ping"));
            await consume(CreateTaskEvent(sequence: 1), cancellationToken).ConfigureAwait(false);
            await consume(CreateTaskEvent(sequence: 3), cancellationToken).ConfigureAwait(false);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class SnapshotHttpMessageHandler(bool capabilitiesAvailable)
        : HttpMessageHandler
    {
        private int _tasksRequestCount;

        public int TasksRequestCount => Volatile.Read(ref _tasksRequestCount);

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var path = request.RequestUri?.AbsolutePath ?? string.Empty;
            if (path == "/api/v1/tasks")
            {
                Interlocked.Increment(ref _tasksRequestCount);
            }
            return Task.FromResult(path switch
            {
                "/api/v1/health"       => Json(HttpStatusCode.OK, HealthJson),
                "/api/v1/capabilities" => capabilitiesAvailable
                    ? Json(HttpStatusCode.OK, CapabilitiesJson)
                    : Json(HttpStatusCode.NotFound, NotFoundJson),
                "/api/v1/tasks"        => Json(HttpStatusCode.OK, TasksJson),
                _                       => Json(HttpStatusCode.NotFound, NotFoundJson),
            });
        }

        private static HttpResponseMessage Json(HttpStatusCode statusCode, string content) => new(
            statusCode)
        {
            Content = new StringContent(content, Encoding.UTF8, "application/json"),
        };

        private const string HealthJson = """
        {
          "status": "ok",
          "database": "ok",
          "version": "2.3.0"
        }
        """;

        private const string CapabilitiesJson = """
        {
          "schema_version": "2.3.0",
          "features": {
            "local_agent": true,
            "durable_queue": true,
            "mcp_hub": true,
            "dashboard": false,
            "task_detail": false,
            "task_pause_resume": false,
            "approval_list": false,
            "approval_digest": false,
            "result_list": false,
            "result_preview": false,
            "health_detailed": false,
            "logs_query": false,
            "manual_goal": false,
            "connector_contract_v1": true,
            "handoff_contract_v1": true,
            "windows_worker": false
          },
          "contract_versions": {
            "connector": "1.0.0",
            "handoff_return": "1.0.0"
          },
          "cloud_upload": "manual_approval_only"
        }
        """;

        private const string TasksJson = """
        [
          {
            "task_id": "task-0001",
            "parent_task_id": null,
            "project_id": null,
            "task_type": "analysis",
            "status": "Queued",
            "priority": 100,
            "resource_tag": null,
            "payload": {},
            "attempt_count": 0,
            "max_attempts": 3,
            "timeout_seconds": 3600,
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
            "error_code": null,
            "error_message": null
          }
        ]
        """;

        private const string NotFoundJson = """
        {
          "error": {
            "code": "NOT_FOUND",
            "message": "能力接口不存在。",
            "retryable": false,
            "trace_id": "trace-not-found"
          }
        }
        """;
    }
}
