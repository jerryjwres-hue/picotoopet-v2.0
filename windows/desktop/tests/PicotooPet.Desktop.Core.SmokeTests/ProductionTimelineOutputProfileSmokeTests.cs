using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 C005 plan timeline/profile facts；Windows 只绑定 Core 已冻结的 task 值。</summary>
internal static class ProductionTimelineOutputProfileSmokeTests
{
    public static void Run()
    {
        const string json = """
            {
              "schema_version": "1.0",
              "production_profile": "production.comfyui.v1",
              "production_job_id": "00000000-0000-4000-8000-000000000200",
              "creative_package_id": "00000000-0000-4000-8000-000000000190",
              "creative_package_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "project_key": "pet-dryer-us",
              "output_profile_id": "video.vertical.v1",
              "target_runtime_ms": 3000,
              "tasks": [
                {
                  "production_task_id": "00000000-0000-4000-8000-000000000201",
                  "shot_id": "shot-1",
                  "order": 1,
                  "render_intent": "GENERATIVE_VIDEO",
                  "execution_disposition": "Executable",
                  "workflow_id": "comfy.wan22.ti2v5b.t2v.v1",
                  "positive_prompt": "vertical product demonstration",
                  "negative_prompt_policy_id": "wan22.safe-negative.v1",
                  "seed": 1001,
                  "width": 480,
                  "height": 832,
                  "fps": 24,
                  "frame_count": 73,
                  "target_duration_ms": 3000,
                  "trusted_input_asset_ref": null
                }
              ]
            }
            """;

        var plan = JsonSerializer.Deserialize<ProductionPlanRecord>(json)
            ?? throw new InvalidOperationException("C005 Production plan 反序列化失败");
        SmokeAssert.Equal("video.vertical.v1", plan.OutputProfileId, "Windows 丢失 Core output profile identity");
        SmokeAssert.Equal(3000L, plan.TargetRuntimeMs, "Windows 丢失 plan target runtime");
        SmokeAssert.Equal(3000L, plan.Tasks[0].TargetDurationMs, "Windows 丢失 task target duration");

        var template = ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.T2VWorkflowId);
        JsonObject prompt = ComfyWorkflowTemplateValidator.Bind(
            ComfyWorkflowTemplateValidator.T2VWorkflowId,
            template,
            plan.Tasks[0],
            "PicotooPet/production/job/001");

        SmokeAssert.Equal(480, Input(prompt, "Wan22ImageToVideoLatent", "width"), "Windows 未绑定 Core 冻结宽度");
        SmokeAssert.Equal(832, Input(prompt, "Wan22ImageToVideoLatent", "height"), "Windows 未绑定 Core 冻结高度");
        SmokeAssert.Equal(73, Input(prompt, "Wan22ImageToVideoLatent", "length"), "Windows 未绑定 Core 冻结帧数");
        SmokeAssert.Equal(24, Input(prompt, "SaveWEBM", "fps"), "Windows 未绑定 Core 冻结帧率");
    }

    private static int Input(JsonObject prompt, string classType, string field) =>
        prompt
            .Select(item => item.Value?.AsObject())
            .Single(node => string.Equals(
                node?["class_type"]?.GetValue<string>(),
                classType,
                StringComparison.Ordinal))!["inputs"]![field]!.GetValue<int>();
}
