using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>只测试现有创意面板新增的只读呈现，不创建 Job、不接 Comfy、不生成模拟批准。</summary>
internal static class StudioStoryPackPanelSmokeTests
{
    public static void Run()
    {
        var vm = CreativeIntelligencePanelViewModel.CreateForSmokeTest(
            Array.Empty<CreativeEligibleSourceRecord>());
        SmokeAssert.True(!vm.CanPreviewStoryPack, "空 StoryPack 不应允许预览");
        // 一键示例仅改内存草稿，不会接 Mac、创建 Job 或开启 GPU。
        vm.LoadMaotaiDinnerPilotDraft();
        SmokeAssert.True(vm.CanPreviewStoryPack, "三镜头草稿载入后应允许手动只读检查");
        var pilot = JsonElement.Parse(vm.StoryPackJson);
        SmokeAssert.Equal("maotai_dinner_p0_draft_v1",
            pilot.GetProperty("episode_id").GetString(), "载入了错误的首片示例");
        SmokeAssert.Equal(3, pilot.GetProperty("shots").GetArrayLength(),
            "首片故事必须有三个真实动作镜头");
        SmokeAssert.True(pilot.GetProperty("character_ref").GetString()!.StartsWith("draft_", StringComparison.Ordinal)
            && pilot.GetProperty("scene_ref").GetString()!.StartsWith("draft_", StringComparison.Ordinal),
            "示例不得伪装成已经验证的参考资产");
        SmokeAssert.True(pilot.GetProperty("shots")[1].GetProperty("action").GetString()!.Contains("坐好", StringComparison.Ordinal)
            && pilot.GetProperty("shots")[2].GetProperty("action").GetString()!.Contains("第一口", StringComparison.Ordinal),
            "首片不能退化成没有起承转合的纯技术空镜头");
        SmokeAssert.True(vm.StoryPackPreviewStatus.Contains("未验证", StringComparison.Ordinal),
            "载入示例必须保留未验证资产的清晰提示");
        vm.StoryPackJson = "{}";
        SmokeAssert.True(vm.CanPreviewStoryPack, "输入存在后应支持手动只读预览");
        SmokeAssert.True(vm.StoryPackPreviewStatus.Contains("草稿已改变", StringComparison.Ordinal),
            "新草稿不得保留旧的已验证结果");

        var valid = JsonElement.Parse("""
        {
          "validated": true,
          "can_queue": false,
          "shot_count": 3,
          "output": {
            "planned_duration_s": 12,
            "width": 832,
            "height": 480,
            "fps": 24,
            "frames_per_shot": 97,
            "planned_frames": 291
          },
          "production_compilation": {"executable": false},
          "core23_compatibility": {"gpu_post_authorized": false},
          "owner_review_subject": {"owner_approved": false},
          "asset_record_checks": [
            {"content_integrity_verified": false},
            {"content_integrity_verified": false},
            {"content_integrity_verified": true}
          ]
        }
        """);
        var summary = CreativeIntelligencePanelViewModel.FormatReadOnlyStoryPackPreview(valid);
        SmokeAssert.True(summary.Contains("3 镜头", StringComparison.Ordinal)
            && summary.Contains("12 秒", StringComparison.Ordinal)
            && summary.Contains("832×480", StringComparison.Ordinal)
            && summary.Contains("每镜 97 帧", StringComparison.Ordinal)
            && summary.Contains("共 291 渲染帧", StringComparison.Ordinal)
            && summary.Contains("未验证资产 2 项", StringComparison.Ordinal)
            && summary.Contains("GPU HOLD", StringComparison.Ordinal),
            "3 镜头预览必须保留资产缺口和明确 HOLD");

        // 客户端不能把不完整的只读回执、伪造 GPU 放行或 Owner 标志显示为成功。
        foreach (var rejected in new[]
        {
            "{}",
            "{\"validated\":true,\"can_queue\":true}",
            "{\"validated\":true,\"can_queue\":false,\"production_compilation\":{\"executable\":true}}",
            "{\"validated\":true,\"can_queue\":false,\"production_compilation\":{\"executable\":false},"
            + "\"core23_compatibility\":{\"gpu_post_authorized\":true}}",
        })
        {
            var result = CreativeIntelligencePanelViewModel.FormatReadOnlyStoryPackPreview(
                JsonElement.Parse(rejected));
            SmokeAssert.True(result.Contains("UNVERIFIED", StringComparison.Ordinal),
                "不完整或伪造授权不得显示为已通过");
        }

        vm.StoryPackJson = string.Empty;
        SmokeAssert.True(!vm.CanPreviewStoryPack, "清空草稿应立即关闭按钮");
    }
}
