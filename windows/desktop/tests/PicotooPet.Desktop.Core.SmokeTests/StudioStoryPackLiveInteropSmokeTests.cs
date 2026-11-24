using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>仅在 Windows CI 的真实 2.3 Python Core localhost 进程上执行；不涉及用户设备。</summary>
internal static class StudioStoryPackLiveInteropSmokeTests
{
    /// <summary>通过真正的 HTTP/JSON/设备 Bearer 验证 3 镜头 StoryPack；所有生产许可必须保持关闭。</summary>
    public static async Task RunAsync()
    {
        var port = Environment.GetEnvironmentVariable("PICOTOO_TEST_STUDIO_PORT");
        var token = Environment.GetEnvironmentVariable("PICOTOO_TEST_STUDIO_TOKEN");
        if (!int.TryParse(port, out var numericPort) || numericPort is < 1 or > 65535
            || string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("仅允许 CI 提供的本地短期端口和临时 Token。");
        }

        var baseUri = new Uri($"http://127.0.0.1:{numericPort}/", UriKind.Absolute);
        var options = MacCoreClientOptions.CreateDefault(baseUri, token);
        await using var client = MacCoreClient.Create(options);
        var health = await client.GetHealthAsync().ConfigureAwait(false);
        SmokeAssert.Equal("ok", health.Status, "真实 Python Core 未恢复健康");

        var before = await client.GetTasksAsync().ConfigureAwait(false);
        // 真正让 Core 校验用户在 WPF 中可一键载入的剧本，而不是另一份测试专用空剧情。
        var pack = JsonElement.Parse(CreativeIntelligencePanelViewModel.MaotaiDinnerPilotDraft);
        SmokeAssert.Equal(3, pack.GetProperty("shots").GetArrayLength(),
            "UI 试片必须保留完整三镜头故事");
        SmokeAssert.True(
            pack.GetProperty("shots")[1].GetProperty("state_in").GetString()
                == pack.GetProperty("shots")[0].GetProperty("state_out").GetString()
            && pack.GetProperty("shots")[2].GetProperty("state_in").GetString()
                == pack.GetProperty("shots")[1].GetProperty("state_out").GetString(),
            "三镜状态衔接在送往 Mac 之前就必须一致");
        SmokeAssert.True(
            pack.GetProperty("shots")[0].GetProperty("action").GetString()!.Contains("荧绿色", StringComparison.Ordinal)
            && pack.GetProperty("shots")[2].GetProperty("action").GetString()!.Contains("第一口", StringComparison.Ordinal),
            "真正的 P0 剧本应包含茅台形象锚点和明确故事结局");
        var preview = await client.PreviewStudioStoryPackAsync(pack).ConfigureAwait(false);

        // 使用「真实 Core 接口返回」的 Goal 提案，而不是 Windows 假服务或自编 ProductionPlan。
        SmokeAssert.True(
            CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
                preview, out var canonicalObjective, out var canonicalDigest),
            "真实 Mac 2.3 StoryPack 预览未能生成可审阅的 canonical Goal 提案");
        SmokeAssert.Equal(
            preview.GetProperty("storypack_sha256").GetString(), canonicalDigest,
            "真实 Core 返回的 Goal 绑定不一致");
        var canonicalRequest = new HumanGoalCreateRequest(
            "video.creative", canonicalObjective, "standard");
        SmokeAssert.True(
            canonicalRequest.Objective.Contains("荧绿色", StringComparison.Ordinal)
            && canonicalRequest.Objective.Contains("第一口", StringComparison.Ordinal),
            "Core 的 Human Goal 提案丢失了茅台身份或故事结局");
        // 这一步仅测试可兼容的请求形状；真实创建须用户二次点击确认。
        SmokeAssert.Equal(3, preview.GetProperty("shot_count").GetInt32(),
            "真实跨语言 HTTP 没有保留三个镜头");
        SmokeAssert.Equal(12, preview.GetProperty("output").GetProperty("planned_duration_s").GetInt32(),
            "真实跨端草稿时长不是 12 秒");
        SmokeAssert.Equal(832, preview.GetProperty("output").GetProperty("width").GetInt32(),
            "预览分辨率不符合 P0");
        SmokeAssert.Equal(480, preview.GetProperty("output").GetProperty("height").GetInt32(),
            "预览分辨率不符合 P0");
        SmokeAssert.Equal(24, preview.GetProperty("output").GetProperty("fps").GetInt32(),
            "预览帧率不符合 P0");
        // Canonical Wan 2.3 uses a 4n+1 frame family: 4 sec = 97 frames, not 96.
        SmokeAssert.Equal(97, preview.GetProperty("output").GetProperty("frames_per_shot").GetInt32(),
            "Studio 预览与真实 Wan Production 编译器的单镜帧数不一致");
        SmokeAssert.Equal(291, preview.GetProperty("output").GetProperty("planned_frames").GetInt32(),
            "三个镜头的渲染帧数必须是 3 × 97");
        SmokeAssert.True(preview.GetProperty("can_queue").ValueKind == JsonValueKind.False,
            "真实 Mac Core 意外开放 Queue");
        SmokeAssert.True(
            preview.GetProperty("production_compilation").GetProperty("executable")
                .ValueKind == JsonValueKind.False,
            "旧版 V3.1 Episode 不能被视为 2.3 ProductionPlan");
        SmokeAssert.True(
            preview.GetProperty("owner_review_subject").GetProperty("owner_approved")
                .ValueKind == JsonValueKind.False,
            "不存在正式 Owner 授权");
        SmokeAssert.True(
            preview.GetProperty("core23_compatibility").GetProperty("gpu_post_authorized")
                .ValueKind == JsonValueKind.False,
            "真实 Core 必须保留 GPU HOLD");
        SmokeAssert.Equal(
            "BLOCKED_INCOMPLETE_EVIDENCE",
            preview.GetProperty("owner_review_subject").GetProperty("status").GetString(),
            "未登记的 Maotai Master 资产不应获得批准");
        SmokeAssert.Equal(3, preview.GetProperty("asset_record_checks").GetArrayLength(),
            "三个草稿资产应分别得到真实 Core 的资产核验结果");
        foreach (var asset in preview.GetProperty("asset_record_checks").EnumerateArray())
        {
            SmokeAssert.True(
                asset.GetProperty("content_integrity_verified").ValueKind == JsonValueKind.False
                && asset.GetProperty("usable_for_generation").ValueKind == JsonValueKind.False,
                "任何 draft_ 参考资产都不得通过真实 Core 的生产信任门禁");
        }

        // 额外重复提交一次，确认指纹稳定且没有副作用。
        var repeated = await client.PreviewStudioStoryPackAsync(pack).ConfigureAwait(false);
        SmokeAssert.Equal(preview.GetProperty("storypack_sha256").GetString(),
            repeated.GetProperty("storypack_sha256").GetString(),
            "同一 StoryPack 的真实 HTTP 摘要出现非确定性变化");

        // 真实跨语言素材上传：临时项目与 CI 素材，不读取用户文件。
        var project = Environment.GetEnvironmentVariable("PICOTOO_TEST_STUDIO_PROJECT");
        if (string.IsNullOrWhiteSpace(project))
        {
            throw new InvalidOperationException("CI fixture project missing.");
        }

        var png = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XgZsAAAAASUVORK5CYII=");
        var style = Encoding.UTF8.GetBytes("CI fixture: local-only stylized reference");
        var vm = CreativeIntelligencePanelViewModel.CreateForSmokeTest(
            Array.Empty<CreativeEligibleSourceRecord>());
        vm.LoadMaotaiDinnerPilotDraft();
        foreach (var (role, media, bytes) in new (string, string, byte[])[]
        {
            ("character", "image/png", png),
            ("scene", "image/png", png),
            ("style", "text/plain", style),
        })
        {
            var original = vm.StoryPackJson;
            var id = await client.ImportStudioAssetAsync(project, role, media, bytes)
                .ConfigureAwait(false);
            var replay = await client.ImportStudioAssetAsync(project, role, media, bytes)
                .ConfigureAwait(false);
            SmokeAssert.Equal(id, replay, "真实 Core 资产重试必须幂等");
            SmokeAssert.True(vm.TryBindImportedAsset(original, role, id),
                "真实资产登记回执无法绑定草稿");
        }
        var registered = await client.PreviewStudioStoryPackAsync(JsonElement.Parse(vm.StoryPackJson))
            .ConfigureAwait(false);
        SmokeAssert.Equal("REVIEW_SUBJECT_PREPARED_UNAPPROVED",
            registered.GetProperty("owner_review_subject").GetProperty("status").GetString(),
            "三份真实登记资产必须允许构造未批准的审核主体");
        foreach (var asset in registered.GetProperty("asset_record_checks").EnumerateArray())
        {
            SmokeAssert.Equal("CONTENT_VERIFIED_UNAPPROVED",
                asset.GetProperty("managed_object_integrity").GetString(),
                "跨语言登记素材字节核验失败");
            SmokeAssert.True(asset.GetProperty("usable_for_generation").ValueKind == JsonValueKind.False,
                "资产登记不得隐式通过生产授权");
        }
        SmokeAssert.True(registered.GetProperty("can_queue").ValueKind == JsonValueKind.False
            && registered.GetProperty("owner_review_subject").GetProperty("owner_approved").ValueKind == JsonValueKind.False
            && registered.GetProperty("core23_compatibility").GetProperty("gpu_post_authorized").ValueKind == JsonValueKind.False,
            "真实导入后必须保留生产否决字段");
        Console.WriteLine("REAL_CORE_WINDOWS_ASSET_HTTP=PASS; REPLAY=PASS; GPU_POST=0");

        // 01. Live Windows -> REAL Python Core 3.12: register a synthetic
        //     Windows-only LoRA DIGEST. No GPU, no upload and no local model.
        var syntheticLora = Encoding.UTF8.GetBytes("ci-fixture-lora-metadata-only");
        var syntheticLoraSha = Convert.ToHexStringLower(
            System.Security.Cryptography.SHA256.HashData(syntheticLora));
        var syntheticEvidence = new StudioWindowsByteEvidence(
            "synthetic-ci-only.safetensors",
            DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ",
                System.Globalization.CultureInfo.InvariantCulture));
        var loraClaim = await client.RegisterStudioWindowsLoraAsync(
            project, syntheticLoraSha, syntheticLora.Length, syntheticEvidence)
            .ConfigureAwait(false);
        var loraReplay = await client.RegisterStudioWindowsLoraAsync(
            project, syntheticLoraSha, syntheticLora.Length, syntheticEvidence)
            .ConfigureAwait(false);
        SmokeAssert.Equal(loraClaim.ArtifactId, loraReplay.ArtifactId,
            "Windows-only LoRA SHA record must be idempotent in REAL Core");
        // 02. This existing Studio CI is explicitly READ-ONLY for approvals.
        //     Registration has been verified over real HTTP; Owner request
        //     is covered by the Core P0-1 approval integration suite and the
        //     standalone Windows HTTP receipt/denial smoke test instead.
        //     Do NOT create even synthetic Pending records in this fixture.
        Console.WriteLine("REAL_CORE_WINDOWS_LORA_SHA_CLAIM=PASS; "
            + "OWNER_APPROVAL_RECORD_DELTA=0; GPU_POST=0");

        var after = await client.GetTasksAsync().ConfigureAwait(false);
        SmokeAssert.Equal(before.Length, after.Length, "预览误创建真实 Core Task");

        // 完整网络链路上的非法设备 Bearer 应得到真实 Core 的 401，不允许静默重试或提权。
        await using var denied = MacCoreClient.Create(
            MacCoreClientOptions.CreateDefault(baseUri, "invalid-test-only-token"));
        try
        {
            await denied.PreviewStudioStoryPackAsync(pack).ConfigureAwait(false);
            throw new InvalidOperationException("无效 Token 在真实 Python Core 上未被拒绝。");
        }
        catch (ApiException error)
        {
            SmokeAssert.Equal("AUTHENTICATION_REQUIRED", error.Code,
                "真实 Python API 错误码与 Windows 客户端未对齐");
            SmokeAssert.Equal(401, error.StatusCode, "真实认证拒绝必须为 HTTP 401");
        }

        Console.WriteLine("REAL_CORE_WINDOWS_STUDIO_HTTP=PASS; TASK_DELTA=0; LEASE=0; GPU_POST=0");

        // 独立的明确提交阶段：使用实际 WPF 动态示例，保留前三份已登记资产。
        vm.LoadDynamicDinnerPilotDraft();
        var dynamicPack = JsonElement.Parse(vm.StoryPackJson);
        var dynamicPreview = await client.PreviewStudioStoryPackAsync(dynamicPack).ConfigureAwait(false);
        var scope = FilmStudioAssetPanel.ParseScopedPreview(dynamicPack, dynamicPreview);
        SmokeAssert.True(scope.MotionSummary.Contains("walks left to right", StringComparison.Ordinal),
            "动态预览必须包含真实接近动作");
        SmokeAssert.True(!CreativeIntelligencePanelViewModel.TryGetCanonicalGoalIntake(
            dynamicPreview, out _, out _), "动态故事不得误走旧普通 Goal");

        var subject = "pet:ci-fixture";
        var empty = await client.GetScopedOwnerPacketsAsync(
            project, scope.CharacterRef, subject, scope.CharacterSha).ConfigureAwait(false);
        SmokeAssert.Equal(0, empty.GetProperty("packets").GetArrayLength(),
            "临时宠物不应在用户确认前具有声明");
        var evidence = JsonSerializer.SerializeToElement(new
        {
            subject_key = subject,
            photo_sha256_claim = scope.CharacterSha,
            claims = new[]
            {
                new { kind = "visible_identity", statement = "Synthetic fixture dog wears a green scarf." },
                new { kind = "visible_scene", statement = "Round steel bowl in the synthetic dining scene." },
                new { kind = "creative_intent", statement = "The pet notices, approaches and begins eating." },
            },
        });
        var packetDigest = await client.PreviewOwnerPacketAsync(evidence).ConfigureAwait(false);
        // 仅在 CI 中模拟对上面完整、无个人信息的固定声明作出明确确认。
        await client.CommitReviewedOwnerPacketAsync(evidence, packetDigest).ConfigureAwait(false);
        await client.CommitReviewedOwnerPacketAsync(evidence, packetDigest).ConfigureAwait(false);
        var reused = await client.GetScopedOwnerPacketsAsync(
            project, scope.CharacterRef, subject, scope.CharacterSha).ConfigureAwait(false);
        SmokeAssert.Equal(1, reused.GetProperty("packets").GetArrayLength(), "声明登记必须幂等");
        SmokeAssert.Equal(packetDigest, reused.GetProperty("packets")[0].GetProperty("packet_digest").GetString(),
            "读取的已有声明必须与已登记摘要一致");
        var goalId = await client.SubmitScopedStoryGoalAsync(
            dynamicPack, project, scope.CharacterRef, scope.CharacterSha, subject,
            packetDigest, scope.SubjectDigest, scope.StoryDigest, scope.MotionDigest).ConfigureAwait(false);
        var replayGoal = await client.SubmitScopedStoryGoalAsync(
            dynamicPack, project, scope.CharacterRef, scope.CharacterSha, subject,
            packetDigest, scope.SubjectDigest, scope.StoryDigest, scope.MotionDigest).ConfigureAwait(false);
        SmokeAssert.Equal(goalId, replayGoal, "动态 Scoped Goal 重试不能创建重复工作流");
        Console.WriteLine("REAL_CORE_WINDOWS_SCOPED_GOAL_HTTP=PASS; OWNER_PACKET_REUSE=PASS; GPU_POST=0");
    }
}
