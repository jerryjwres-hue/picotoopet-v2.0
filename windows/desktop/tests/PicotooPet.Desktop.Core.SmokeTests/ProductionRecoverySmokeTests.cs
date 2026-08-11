using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 lease reclaim 恢复：Core 已提交 Succeeded 的 shot 不得再次进入 Windows resume plan。</summary>
internal static class ProductionRecoverySmokeTests
{
    public static void Run()
    {
        var firstTask = PlanTask("00000000-0000-4000-8000-000000000201", "shot-1", 1);
        var secondTask = PlanTask("00000000-0000-4000-8000-000000000202", "shot-2", 2);
        var plan = new ProductionPlanRecord(
            "1.0",
            "production.comfyui.v1",
            "00000000-0000-4000-8000-000000000200",
            "00000000-0000-4000-8000-000000000190",
            new string('a', 64),
            "pet-dryer-us",
            [firstTask, secondTask]);
        var completed = TaskRecord(firstTask, "Succeeded", "outputs/shot-1.webm", new string('b', 64));
        var pending = TaskRecord(secondTask, "Ready", null, null);

        var claim = new ProductionClaimRecord(
            plan.ProductionJobId,
            "windows-production-smoke",
            "0123456789abcdef0123456789abcdef",
            DateTimeOffset.UtcNow.AddMinutes(2),
            plan,
            [completed, pending]);

        SmokeAssert.True(claim.Tasks.Length == 2, "durable task snapshot 必须完整保留");
        SmokeAssert.True(claim.Plan.Tasks.Length == 1, "resume plan 必须过滤已 Succeeded shot");
        SmokeAssert.True(
            claim.Plan.Tasks[0].ProductionTaskId == secondTask.ProductionTaskId,
            "resume plan 只允许继续未完成 shot");
        SmokeAssert.True(
            claim.Tasks[0].OutputSha256 == new string('b', 64),
            "已完成输出 digest 必须保留用于恢复审计");
    }

    private static ProductionTaskPlanRecord PlanTask(string taskId, string shotId, int order) =>
        new(
            taskId,
            shotId,
            order,
            "GENERATIVE_VIDEO",
            "Executable",
            "comfy.wan22.ti2v5b.t2v.v1",
            $"product demonstration {order}",
            "wan22.safe-negative.v1",
            1000 + order,
            832,
            480,
            24,
            81,
            null);

    private static ProductionTaskRecord TaskRecord(
        ProductionTaskPlanRecord plan,
        string status,
        string? outputRelpath,
        string? outputSha256) =>
        new(
            plan.ProductionTaskId,
            "00000000-0000-4000-8000-000000000200",
            plan.ShotId,
            plan.Order,
            plan.RenderIntent,
            plan.ExecutionDisposition,
            plan.WorkflowId,
            plan,
            status,
            status == "Succeeded" ? 1 : 0,
            status == "Succeeded" ? "prompt-completed" : null,
            outputRelpath,
            outputSha256,
            status == "Succeeded" ? 1024 : null,
            status == "Succeeded" ? "video/webm" : null,
            status == "Succeeded" ? plan.Width : null,
            status == "Succeeded" ? plan.Height : null,
            status == "Succeeded" ? plan.FrameCount : null,
            status == "Succeeded" ? plan.Fps : null,
            null,
            null,
            DateTimeOffset.UtcNow.AddMinutes(-5),
            DateTimeOffset.UtcNow,
            status == "Succeeded" ? DateTimeOffset.UtcNow : null);
}
