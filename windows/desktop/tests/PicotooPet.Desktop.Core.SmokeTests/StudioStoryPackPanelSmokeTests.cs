using System.Text.Json;
using System.Text.Json.Nodes;
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

        // 已校验的 StoryPack 可以作为真正 Human Goal 的「用户确认提案」，但绝不直接创建生产任务。
        var candidate = JsonNode.Parse(valid.GetRawText())!;
        var sha = new string('a', 64);
        candidate["storypack_sha256"] = sha;
        candidate["canonical_goal_intake"] = JsonSerializer.SerializeToNode(new
        {
            contract = "picotoo.storypack.canonical-goal-intake.v1",
            storypack_sha256 = sha,
            goal_type = "video.creative",
            depth = "standard",
            local_video_preferred = true,
            objective = "纯宠物视频，3个镜头，每个镜头4秒；请使用原有 Core 研究与 Creative 通路。",
            objective_character_count = "纯宠物视频，3个镜头，每个镜头4秒；请使用原有 Core 研究与 Creative 通路。".Length,
            ready_for_user_submission = true,
            blocking_reasons = Array.Empty<string>(),
            requires_explicit_user_action = true,
            source_evidence_verified = false,
            creative_package_approved = false,
            production_plan_executable = false,
            owner_approved = false,
            gpu_post_authorized = false,
        });
        var ready = JsonElement.Parse(candidate.ToJsonString());
        SmokeAssert.True(
            CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
                ready, out var intakeObjective, out var intakeDigest)
            && intakeDigest == sha && intakeObjective.Contains("纯宠物视频", StringComparison.Ordinal),
            "已验证提案须能从 Core 只读响应进入唯一现有 Goal 输入合同");

        foreach (var (field, value) in new (string, bool)[]
        {
            ("ready_for_user_submission", false),
            ("requires_explicit_user_action", false),
            ("source_evidence_verified", true),
            ("creative_package_approved", true),
            ("production_plan_executable", true),
            ("owner_approved", true),
            ("gpu_post_authorized", true),
        })
        {
            var forged = JsonNode.Parse(candidate.ToJsonString())!;
            forged["canonical_goal_intake"]![field] = value;
            SmokeAssert.True(
                !CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
                    JsonElement.Parse(forged.ToJsonString()), out _, out _),
                $"伪造的 {field} 标志不得允许创建 Goal");
        }

        foreach (var field in new[] { "storypack_sha256", "objective", "goal_type" })
        {
            var incomplete = JsonNode.Parse(candidate.ToJsonString())!;
            (incomplete["canonical_goal_intake"] as JsonObject)!.Remove(field);
            SmokeAssert.True(
                !CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
                    JsonElement.Parse(incomplete.ToJsonString()), out _, out _),
                $"缺少 {field} 不得显示 Goal 已就绪");
        }

        var stale = JsonNode.Parse(candidate.ToJsonString())!;
        stale["canonical_goal_intake"]!["storypack_sha256"] = new string('b', 64);
        SmokeAssert.True(
            !CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
                JsonElement.Parse(stale.ToJsonString()), out _, out _),
            "响应体与请求 StoryPack 摘要不一致必须拒绝");

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

        // 正式导入只替换指定引用，与上一版故事的观察/审批完全分离。
        vm.LoadMaotaiDinnerPilotDraft();
        var draft = JsonNode.Parse(vm.StoryPackJson)!.AsObject();
        var originalCharacter = draft["character_ref"]!.GetValue<string>();
        var originalScene = draft["scene_ref"]!.GetValue<string>();
        var secondShot = draft["shots"]![1]!.AsObject();
        secondShot["cast_refs"] = JsonSerializer.SerializeToNode(new[] { originalCharacter });
        secondShot["scene_ref"] = originalScene;
        vm.StoryPackJson = draft.ToJsonString();
        var captured = vm.StoryPackJson;
        var characterId = "asset-" + new string('a', 64);
        var sceneId = "asset-" + new string('b', 64);
        var styleId = "asset-" + new string('c', 64);
        SmokeAssert.True(vm.TryBeginAssetImport(captured), "素材登记必须冻结当前预览");
        SmokeAssert.True(!vm.CanPreviewStoryPack && !vm.CanCreateStoryGoal, "上传期间必须禁用预览和旧 Goal");
        SmokeAssert.True(!vm.TryBeginAssetImport(captured), "重复登记操作必须拒绝");
        SmokeAssert.True(vm.TryBindImportedAsset(captured, "character", characterId), "角色回执应绑定精确角色引用");
        vm.EndAssetImport();
        SmokeAssert.True(vm.CanPreviewStoryPack && !vm.CanCreateStoryGoal, "仅重新预览可用，不能复用旧 Goal");
        SmokeAssert.True(!vm.TryBindImportedAsset(captured, "scene", sceneId), "旧快照不得覆盖已修改草稿");
        SmokeAssert.True(vm.TryBindImportedAsset(vm.StoryPackJson, "scene", sceneId), "场景回执应绑定场景引用");
        SmokeAssert.True(vm.TryBindImportedAsset(vm.StoryPackJson, "style", styleId), "风格回执应绑定风格锁");
        var bound = JsonElement.Parse(vm.StoryPackJson);
        SmokeAssert.Equal(characterId, bound.GetProperty("character_ref").GetString(), "主角色 ID 不匹配");
        SmokeAssert.Equal(characterId, bound.GetProperty("shots")[1].GetProperty("cast_refs")[0].GetString(), "显式镜头角色没有同步");
        SmokeAssert.Equal(sceneId, bound.GetProperty("shots")[1].GetProperty("scene_ref").GetString(), "显式镜头场景没有同步");
        SmokeAssert.Equal(styleId, bound.GetProperty("style_ref").GetString(), "风格 ID 不匹配");
        SmokeAssert.Equal(pilot.GetProperty("shots")[1].GetProperty("action").GetString(),
            bound.GetProperty("shots")[1].GetProperty("action").GetString(), "登记不得改写导演动作");
        SmokeAssert.True(!vm.CanCreateStoryGoal && vm.StoryPackPreviewStatus.Contains("重新只读检查", StringComparison.Ordinal),
            "素材改变必须令原预览与 Goal 准入失效");
        Console.WriteLine("STUDIO_ASSET_DRAFT_BINDING=PASS; STALE_DRAFT_REJECTED=PASS");

        vm.StoryPackJson = string.Empty;
        SmokeAssert.True(!vm.CanPreviewStoryPack, "清空草稿应立即关闭按钮");
    }
}
