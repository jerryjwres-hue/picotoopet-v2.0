using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Worker 状态解析和旧服务保守降级。</summary>
internal static class WorkerStatusSmokeTests
{
    public static void Run()
    {
        var json = """
            {
              "schema_version": "2.3.0",
              "available": false,
              "state": "not_deployed",
              "reason": "Mac 任务执行器尚未部署；Queued 任务不会自动执行。",
              "worker_id": null,
              "supported_task_types": [],
              "observed_at": "2026-08-02T00:00:00Z"
            }
            """;

        var response = JsonSerializer.Deserialize<WorkerStatusResponse>(
            json,
            new JsonSerializerOptions(JsonSerializerDefaults.Web));
        SmokeAssert.True(response is not null, "Worker 状态 JSON 未解析");
        SmokeAssert.True(!response.Available, "未部署 Worker 不得标记可用");
        SmokeAssert.Equal("not_deployed", response.State, "Worker 状态错误");
        SmokeAssert.Equal(0, response.SupportedTaskTypes.Count, "未部署 Worker 不应声明任务类型");

        var fallback = WorkerSnapshot.NotDeployed;
        SmokeAssert.True(!fallback.Available, "404 降级不得标记 Worker 在线");
        SmokeAssert.Equal("not_deployed", fallback.State, "404 降级状态错误");
    }
}
