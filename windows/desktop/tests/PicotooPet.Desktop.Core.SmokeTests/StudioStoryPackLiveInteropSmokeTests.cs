using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;

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
    }
}
