using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 2.3.21.1 Business Pipeline REST 路径与严格 create payload。</summary>
internal static class BusinessPipelineClientSmokeTests
{
    public static async Task RunAsync()
    {
        var handler = new FakeHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8765/"),
        };
        await using var client = new MacCoreBusinessPipelineClient(http, "0123456789abcdef0123456789abcdef");

        var created = await client.CreateRunAsync(
            new BusinessPipelineRunCreateRequest(
                "00000000-0000-4000-8000-000000000021",
                "amazon.reviews_export.v1",
                "pipeline-smoke-001")).ConfigureAwait(false);
        SmokeAssert.True(created.AdapterProfile == "amazon.reviews_export.v1", "Pipeline create profile 解析错误。");

        var runs = await client.GetRunsAsync().ConfigureAwait(false);
        SmokeAssert.True(runs.Length == 1, "Pipeline list 数量错误。");
        _ = await client.GetRunAsync(created.PipelineRunId).ConfigureAwait(false);
        _ = await client.ReconcileAsync(created.PipelineRunId).ConfigureAwait(false);
        var returnPackage = await client.GetReturnPackageAsync(created.PipelineRunId).ConfigureAwait(false);
        SmokeAssert.True(returnPackage is not null, "Completed pipeline 应返回 Return Package 元数据。");
        var archive = await client.DownloadReturnPackageAsync(created.PipelineRunId).ConfigureAwait(false);
        SmokeAssert.True(archive.SequenceEqual(new byte[] { 1, 2, 3, 4 }), "Return Package archive 下载错误。");
        var cancelled = await client.CancelAsync(created.PipelineRunId).ConfigureAwait(false);
        SmokeAssert.True(cancelled.Status == "Cancelled", "Pipeline cancel 状态错误。");

        SmokeAssert.True(
            handler.Paths.SequenceEqual(
            [
                "POST /api/v1/business-pipeline/runs",
                "GET /api/v1/business-pipeline/runs?limit=200",
                $"GET /api/v1/business-pipeline/runs/{created.PipelineRunId}",
                $"POST /api/v1/business-pipeline/runs/{created.PipelineRunId}/reconcile",
                $"GET /api/v1/business-pipeline/runs/{created.PipelineRunId}/return-package",
                $"GET /api/v1/business-pipeline/runs/{created.PipelineRunId}/return-package/archive",
                $"POST /api/v1/business-pipeline/runs/{created.PipelineRunId}/cancel",
            ]),
            "Business Pipeline client 访问了未批准 REST 路径。");
        SmokeAssert.True(handler.CreateBody is not null, "Pipeline create body 缺失。");
        SmokeAssert.True(handler.CreateBody!.Contains("\"work_package_id\"", StringComparison.Ordinal), "create body 缺 work_package_id。");
        SmokeAssert.True(handler.CreateBody.Contains("\"adapter_profile\"", StringComparison.Ordinal), "create body 缺 adapter_profile。");
        SmokeAssert.True(handler.CreateBody.Contains("\"idempotency_key\"", StringComparison.Ordinal), "create body 缺 idempotency_key。");
        foreach (var forbidden in new[] { "model_id", "endpoint", "workflow", "path", "command", "provider" })
        {
            SmokeAssert.True(!handler.CreateBody.Contains($"\"{forbidden}\"", StringComparison.Ordinal),
                $"Pipeline create body 泄露禁止字段：{forbidden}");
        }
    }

    private sealed class FakeHandler : HttpMessageHandler
    {
        private const string RunId = "00000000-0000-4000-8000-000000000022";
        public List<string> Paths { get; } = [];
        public string? CreateBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var pathAndQuery = request.RequestUri?.PathAndQuery ?? string.Empty;
            Paths.Add($"{request.Method.Method} {pathAndQuery}");
            if (request.Method == HttpMethod.Post && pathAndQuery == "/api/v1/business-pipeline/runs")
            {
                CreateBody = await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                return Json(Run("Completed"));
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == "/api/v1/business-pipeline/runs?limit=200")
            {
                return Json($"[{Run("Completed")}]");
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/business-pipeline/runs/{RunId}")
            {
                return Json(Run("Completed"));
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/business-pipeline/runs/{RunId}/reconcile")
            {
                SmokeAssert.True(request.Content is null, "reconcile 不应发送 request body。");
                return Json(Run("Completed"));
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/business-pipeline/runs/{RunId}/return-package")
            {
                return Json(ReturnPackage());
            }
            if (request.Method == HttpMethod.Get && pathAndQuery == $"/api/v1/business-pipeline/runs/{RunId}/return-package/archive")
            {
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent([1, 2, 3, 4]),
                };
            }
            if (request.Method == HttpMethod.Post && pathAndQuery == $"/api/v1/business-pipeline/runs/{RunId}/cancel")
            {
                SmokeAssert.True(request.Content is null, "cancel 不应发送 request body。");
                return Json(Run("Cancelled"));
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        private static string Run(string status) => $$"""
        {
          "pipeline_run_id":"{{RunId}}",
          "work_package_id":"00000000-0000-4000-8000-000000000021",
          "result_package_id":"00000000-0000-4000-8000-000000000023",
          "creative_job_id":"00000000-0000-4000-8000-000000000024",
          "creative_package_id":"00000000-0000-4000-8000-000000000025",
          "production_job_id":"00000000-0000-4000-8000-000000000026",
          "production_package_id":"00000000-0000-4000-8000-000000000027",
          "return_package_id":"00000000-0000-4000-8000-000000000028",
          "project_key":"pet-dryer-us",
          "producer_id":"picotoopet.windows.amazon-adapter",
          "producer_version":"2.3.21.1",
          "adapter_profile":"amazon.reviews_export.v1",
          "status":"{{status}}",
          "quality_outcome":"PASS",
          "failure_code":null,
          "error_message":null,
          "idempotency_key":"pipeline-smoke-001",
          "created_at":"2026-08-11T15:00:00Z",
          "updated_at":"2026-08-11T15:01:00Z",
          "finished_at":"2026-08-11T15:01:00Z"
        }
        """;

        private static string ReturnPackage() => $$"""
        {
          "return_package_id":"00000000-0000-4000-8000-000000000028",
          "pipeline_run_id":"{{RunId}}",
          "package_digest":"{{new string('a', 64)}}",
          "package_relpath":"runtime/business/returns/00000000-0000-4000-8000-000000000028.zip",
          "manifest":{"schema_version":"1.0"},
          "quality_outcome":"PASS",
          "created_at":"2026-08-11T15:01:00Z"
        }
        """;

        private static HttpResponseMessage Json(string content) =>
            new(HttpStatusCode.OK)
            {
                Content = new StringContent(content, Encoding.UTF8, "application/json"),
            };
    }
}
