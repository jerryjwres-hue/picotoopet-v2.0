using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>既有创意面板的可选只读 StoryPack 预览；不增加日常生产步骤或审批捷径。</summary>
public sealed partial class CreativeIntelligencePanelViewModel
{
    private string _storyPackJson = string.Empty;
    private string _storyPackPreviewStatus = "可选：粘贴导演生成的 StoryPack JSON，仅校验镜头与资产。";
    private bool _isStoryPackPreviewBusy;
    private long _storyPackRevision;

    /// <summary>仅保留当前内存中粘贴的草稿；不上传历史、日志或本地缓存。</summary>
    public string StoryPackJson
    {
        get => _storyPackJson;
        set
        {
            if (SetProperty(ref _storyPackJson, value ?? string.Empty))
            {
                Interlocked.Increment(ref _storyPackRevision);
                StoryPackPreviewStatus = "草稿已改变；预览结果不再有效，重新点击校验。";
                RaisePropertyChanged(nameof(CanPreviewStoryPack));
            }
        }
    }

    /// <summary>只显示非秘密的结构摘要、资产缺口和 HOLD 状态，不回显服务端原始证据路径。</summary>
    public string StoryPackPreviewStatus
    {
        get => _storyPackPreviewStatus;
        private set => SetProperty(ref _storyPackPreviewStatus, value);
    }

    public bool IsStoryPackPreviewBusy
    {
        get => _isStoryPackPreviewBusy;
        private set
        {
            if (SetProperty(ref _isStoryPackPreviewBusy, value))
            {
                RaisePropertyChanged(nameof(CanPreviewStoryPack));
            }
        }
    }

    public bool CanPreviewStoryPack =>
        !IsStoryPackPreviewBusy && !string.IsNullOrWhiteSpace(StoryPackJson);

    /// <summary>只向真实 Mac Core 发送一个有界 JSON 草稿；不触发 Creative/Production Task。</summary>
    public async Task PreviewStoryPackAsync(CancellationToken cancellationToken)
    {
        if (!CanPreviewStoryPack)
        {
            return;
        }

        var revision = Volatile.Read(ref _storyPackRevision);
        var source = StoryPackJson;
        if (Encoding.UTF8.GetByteCount(source) > 128 * 1024)
        {
            StoryPackPreviewStatus = "输入过大：最多 128 KiB UTF-8；未发送到 Mac。";
            return;
        }

        IsStoryPackPreviewBusy = true;
        StoryPackPreviewStatus = "正在校验 JSON 与 Mac 已登记资产（只读）……";
        try
        {
            // 使用 JsonElement.Parse 生成独立值，不留下 JsonDocument 资源泄漏。
            var storyPack = JsonElement.Parse(source);
            if (storyPack.ValueKind != JsonValueKind.Object)
            {
                StoryPackPreviewStatus = "必须提交一个 JSON 对象；未发送到 Mac。";
                return;
            }

            var result = await RequireSession().PreviewStudioStoryPackAsync(
                storyPack, cancellationToken);
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                StoryPackPreviewStatus = FormatReadOnlyStoryPackPreview(result);
            }
        }
        catch (JsonException)
        {
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                StoryPackPreviewStatus = "JSON 格式不合法；没有创建任务。";
            }
        }
        catch (ApiException error)
        {
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                StoryPackPreviewStatus = error.StatusCode switch
                {
                    401 => "Mac 设备认证未通过；没有创建任务。",
                    404 => "Mac Core 尚未安装兼容的只读 StoryPack 接口。",
                    413 => "StoryPack 超过服务端大小限制；没有创建任务。",
                    415 => "Mac Core 当前仅支持 JSON StoryPack。",
                    422 => "故事结构或连续性校验失败；没有创建任务。",
                    _ => "预览请求未通过 Mac Core 检查；保持 GPU HOLD。",
                };
            }
        }
        catch (ArgumentException)
        {
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                StoryPackPreviewStatus = "输入格式不符合 StoryPack 只读合同；未提交任务。";
            }
        }
        finally
        {
            IsStoryPackPreviewBusy = false;
        }
    }

    /// <summary>缺少任一否决证据就拒绝展示绿色成功；JSON 摘要本身永远不是 Owner 许可。</summary>
    public static string FormatReadOnlyStoryPackPreview(JsonElement result)
    {
        if (result.ValueKind != JsonValueKind.Object
            || !HasBool(result, "validated", true)
            || !HasBool(result, "can_queue", false)
            || !result.TryGetProperty("production_compilation", out var compilation)
            || !HasBool(compilation, "executable", false)
            || !result.TryGetProperty("core23_compatibility", out var compatibility)
            || !HasBool(compatibility, "gpu_post_authorized", false)
            || !result.TryGetProperty("owner_review_subject", out var owner)
            || !HasBool(owner, "owner_approved", false)
            || !result.TryGetProperty("output", out var output)
            || !result.TryGetProperty("shot_count", out var shots)
            || !shots.TryGetInt32(out var shotCount)
            || !output.TryGetProperty("planned_duration_s", out var length)
            || !length.TryGetInt32(out var seconds)
            || !output.TryGetProperty("width", out var width)
            || !width.TryGetInt32(out var pixelsWide)
            || !output.TryGetProperty("height", out var height)
            || !height.TryGetInt32(out var pixelsHigh)
            || !output.TryGetProperty("fps", out var fps)
            || !fps.TryGetInt32(out var framesPerSecond))
        {
            return "预览响应缺少必要安全字段；结果 UNVERIFIED，禁止进入生产。";
        }

        var unverified = 0;
        if (result.TryGetProperty("asset_record_checks", out var checks)
            && checks.ValueKind == JsonValueKind.Array)
        {
            foreach (var asset in checks.EnumerateArray())
            {
                if (!HasBool(asset, "content_integrity_verified", true))
                {
                    unverified++;
                }
            }
        }
        else
        {
            return "没有资产登记核验结果；预览 UNVERIFIED，禁止进入生产。";
        }

        return $"剧本结构：{shotCount} 镜头 · {seconds} 秒 · {pixelsWide}×{pixelsHigh} · {framesPerSecond}fps。"
            + $" 未验证资产 {unverified} 项。Owner 未批准，GPU HOLD；不可生成或发布。";
    }

    private static bool HasBool(JsonElement json, string property, bool expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(property, out var value)
        && value.ValueKind == (expected ? JsonValueKind.True : JsonValueKind.False);
}
