using System.Net;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证固定诊断端点、幂等键、结果卡片和有界观察策略。</summary>
internal static class DiagnosticSnapshotSmokeTests
{
    private static readonly string[] DiagnosticTaskTypes =
    {
        "system.diagnostic_snapshot",
        "system.noop",
    };

    private static readonly string[] NoopTaskTypes =
    {
        "system.noop",
    };

    private static readonly string[] DiagnosticSections =
    {
        "core",
        "worker",
        "queue",
    };

    private static readonly DiagnosticCheckResult[] HealthyDiagnosticChecks =
    {
        new("core_health", "pass", "CORE_HEALTHY"),
        new("worker_heartbeat", "pass", "WORKER_ONLINE"),
        new("queue_backlog", "pass", "QUEUE_HEALTHY"),
    };

    private static readonly object[] HealthyDiagnosticCheckDocuments =
    {
        new { name = "core_health", status = "pass", reason_code = "CORE_HEALTHY" },
        new { name = "worker_heartbeat", status = "pass", reason_code = "WORKER_ONLINE" },
        new { name = "queue_backlog", status = "pass", reason_code = "QUEUE_HEALTHY" },
    };

    public static async Task RunAsync()
    {
        await VerifyFixedClientContractsAsync().ConfigureAwait(false);
        VerifyResultViewModel();
        VerifyTaskCenterActionRules();
        VerifyBoundedObservationSchedule();
    }

    private static async Task VerifyFixedClientContractsAsync()
    {
        var handler = new RecordingHandler();
        using var httpClient = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(httpClient, "fixture-token");

        var task = await client.CreateDiagnosticSnapshotAsync(
            DiagnosticSnapshotRequest.CreateDefault(),
            "diagnostic-idempotency-1",
            CancellationToken.None).ConfigureAwait(false);
        var result = await client.GetTaskResultAsync(task.TaskId, CancellationToken.None)
            .ConfigureAwait(false);
        var resultViewModel = DiagnosticResultViewModel.FromResult(result);

        SmokeAssert.Equal(
            "api/v1/tasks/system-diagnostic-snapshot",
            handler.Requests[0].Path,
            "诊断创建未使用固定端点");
        SmokeAssert.Equal(
            "diagnostic-idempotency-1",
            handler.Requests[0].IdempotencyKey,
            "诊断创建未保留调用方幂等键");
        SmokeAssert.True(
            !handler.Requests[0].Body.Contains("task_type", StringComparison.Ordinal),
            "诊断创建请求不得包含任意任务类型");
        SmokeAssert.True(
            handler.Requests[0].Body.Contains("\"sections\":[\"core\",\"worker\",\"queue\"]", StringComparison.Ordinal),
            "诊断创建请求没有固定白名单 section");
        SmokeAssert.Equal(
            $"api/v1/tasks/{task.TaskId}/result",
            handler.Requests[1].Path,
            "诊断结果未使用任务关联固定端点");
        SmokeAssert.Equal("1.0", result.SchemaVersion, "诊断结果 schema 解析错误");
        SmokeAssert.True(
            resultViewModel.IsAvailable,
            "HTTP 反序列化后的固定诊断结果未通过 WPF 卡片合同");
    }

    private static void VerifyResultViewModel()
    {
        var result = new DiagnosticSnapshotResult(
            "1.0",
            new DateTimeOffset(2026, 8, 3, 12, 0, 0, TimeSpan.Zero),
            new DiagnosticCoreResult("2.3.0", "online", 2),
            new DiagnosticWorkerResult(
                "worker-m4",
                "online",
                "idle",
                DiagnosticTaskTypes,
                new DateTimeOffset(2026, 8, 3, 12, 0, 0, TimeSpan.Zero)),
            new DiagnosticQueueResult(
                new Dictionary<string, int>
                {
                    ["Completed"] = 3,
                    ["Queued"] = 1,
                },
                2),
            HealthyDiagnosticChecks,
            Array.Empty<string>());

        var viewModel = DiagnosticResultViewModel.FromResult(result);

        SmokeAssert.True(viewModel.IsAvailable, "有效诊断结果未标记可用");
        SmokeAssert.True(
            viewModel.CoreText.Contains("2.3.0", StringComparison.Ordinal),
            "Core 固定卡片缺少版本");
        SmokeAssert.True(
            viewModel.WorkerText.Contains("worker-m4", StringComparison.Ordinal),
            "Worker 固定卡片缺少执行器标识");
        SmokeAssert.True(
            viewModel.QueueText.Contains("Queued=1", StringComparison.Ordinal),
            "Queue 固定卡片缺少聚合计数");
        SmokeAssert.True(
            !viewModel.ChecksText.Contains('{', StringComparison.Ordinal),
            "结果视图不得直接渲染任意 JSON");
    }

    private static void VerifyTaskCenterActionRules()
    {
        var now = new DateTimeOffset(2026, 8, 3, 12, 0, 0, TimeSpan.Zero);
        var completedDiagnostic = new TaskRecord(
            TaskId: "diagnostic-completed",
            ParentTaskId: null,
            ProjectId: null,
            TaskType: "system.diagnostic_snapshot",
            Status: "Completed",
            Priority: 50,
            ResourceTag: "system-diagnostic",
            Payload: JsonSerializer.SerializeToElement(new { schema_version = "1.0" }),
            AttemptCount: 1,
            MaxAttempts: 2,
            TimeoutSeconds: 30,
            CreatedAt: now,
            UpdatedAt: now,
            ErrorCode: null,
            ErrorMessage: null,
            ResultId: "result-1");
        var worker = new WorkerSnapshot(
            SchemaVersion: "2.3.0",
            Available: true,
            State: "online",
            Reason: "idle",
            WorkerId: "worker-m4",
            SupportedTaskTypes: DiagnosticTaskTypes,
            ObservedAt: now);
        var page = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { completedDiagnostic },
            worker);

        SmokeAssert.True(page.CanCreateDiagnostic, "在线且支持诊断的 Worker 应允许创建任务");
        SmokeAssert.True(
            page.SelectedTask?.CanViewDiagnosticResult == true,
            "已完成且有关联结果的诊断任务应允许查看结果");

        var activeDiagnostic = completedDiagnostic with
        {
            TaskId = "diagnostic-running",
            Status = "Running",
            ResultId = null,
        };
        var activePage = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { activeDiagnostic },
            worker);
        SmokeAssert.True(!activePage.CanCreateDiagnostic, "已有活动诊断任务时必须禁止重复创建");
        SmokeAssert.True(
            activePage.DiagnosticCreateReason.Contains("已有", StringComparison.Ordinal),
            "重复创建禁用原因不明确");

        var unsupported = worker with { SupportedTaskTypes = NoopTaskTypes };
        var unsupportedPage = TaskCenterPageViewModel.CreateForSmokeTest(
            Array.Empty<TaskRecord>(),
            unsupported);
        SmokeAssert.True(!unsupportedPage.CanCreateDiagnostic, "Worker 不支持诊断时不得创建");
    }

    private static void VerifyBoundedObservationSchedule()
    {
        var delays = ControlCenterSession.GetDiagnosticObservationDelaysForSmoke();

        SmokeAssert.Equal(5, delays.Count, "诊断观察退避级数错误");
        SmokeAssert.Equal(TimeSpan.FromSeconds(1), delays[0], "首轮观察延迟错误");
        SmokeAssert.Equal(TimeSpan.FromSeconds(10), delays[^1], "观察退避上限错误");
        SmokeAssert.True(
            delays.All(delay => delay <= TimeSpan.FromSeconds(10)),
            "观察退避超过 10 秒上限");
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        public List<RecordedRequest> Requests { get; } = new();

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            var idempotencyKey = request.Headers.TryGetValues("Idempotency-Key", out var values)
                ? values.Single()
                : null;
            Requests.Add(new RecordedRequest(
                request.RequestUri?.PathAndQuery.TrimStart('/') ?? string.Empty,
                body,
                idempotencyKey));

            if (request.RequestUri?.AbsolutePath.EndsWith("/result", StringComparison.Ordinal) == true)
            {
                return JsonResponse(new
                {
                    schema_version = "1.0",
                    generated_at = "2026-08-03T12:00:00+00:00",
                    core = new
                    {
                        version = "2.3.0",
                        health_state = "online",
                        database_schema_version = 2,
                    },
                    worker = new
                    {
                        worker_id = "worker-m4",
                        state = "online",
                        reason = "idle",
                        supported_task_types = DiagnosticTaskTypes,
                        last_heartbeat_at = "2026-08-03T12:00:00+00:00",
                    },
                    queue = new
                    {
                        counts = new Dictionary<string, int> { ["Queued"] = 1 },
                        oldest_queued_age_seconds = 2,
                    },
                    checks = HealthyDiagnosticCheckDocuments,
                    warnings = Array.Empty<string>(),
                });
            }

            return JsonResponse(new
            {
                task_id = "diagnostic-task-1",
                parent_task_id = (string?)null,
                project_id = (string?)null,
                task_type = "system.diagnostic_snapshot",
                status = "Queued",
                priority = 50,
                resource_tag = "system-diagnostic",
                payload = new { schema_version = "1.0", sections = DiagnosticSections },
                attempt_count = 0,
                max_attempts = 2,
                timeout_seconds = 30,
                created_at = "2026-08-03T12:00:00+00:00",
                updated_at = "2026-08-03T12:00:00+00:00",
                error_code = (string?)null,
                error_message = (string?)null,
                result_id = (string?)null,
            });
        }

        private static HttpResponseMessage JsonResponse(object document) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(
                JsonSerializer.Serialize(document),
                Encoding.UTF8,
                "application/json"),
        };
    }

    private sealed record RecordedRequest(
        string Path,
        string Body,
        string? IdempotencyKey);
}
