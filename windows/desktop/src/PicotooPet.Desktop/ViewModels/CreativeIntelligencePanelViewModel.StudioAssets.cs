using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>登记回执只绑定草稿引用；不批准资产、不调用 Goal 或生产。</summary>
public sealed partial class CreativeIntelligencePanelViewModel
{
    private bool _isAssetImportBusy;

    public bool TryBeginAssetImport(string originalDraft)
    {
        // 先冻结当前预览与 Goal 按钮，避免上传期间提交旧故事。
        if (_isAssetImportBusy || IsStoryPackPreviewBusy || _isStoryGoalBusy
            || !string.Equals(originalDraft, StoryPackJson, StringComparison.Ordinal))
        {
            return false;
        }
        _isAssetImportBusy = true;
        Interlocked.Increment(ref _storyPackRevision);
        ResetPreparedGoal();
        StoryPackPreviewStatus = "正在登记本地素材；登记完成后必须重新检查。";
        RaisePropertyChanged(nameof(CanPreviewStoryPack));
        return true;
    }

    public void EndAssetImport()
    {
        if (!_isAssetImportBusy)
        {
            return;
        }
        _isAssetImportBusy = false;
        RaisePropertyChanged(nameof(CanPreviewStoryPack));
        RaisePropertyChanged(nameof(CanCreateStoryGoal));
    }

    public bool TryBindImportedAsset(string originalDraft, string role, string assetId)
    {
        // 01. 网络期间草稿可能已被修改；绝不覆盖新文本或运行中的 Goal。
        if (!string.Equals(originalDraft, StoryPackJson, StringComparison.Ordinal)
            || IsStoryPackPreviewBusy || _isStoryGoalBusy
            || role is not ("character" or "scene" or "style")
            || assetId.Length != 70 || !assetId.StartsWith("asset-", StringComparison.Ordinal)
            || assetId.Skip(6).Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            return false;
        }

        try
        {
            // 02. 只更新角色、场景、风格三类精确引用；不改写剧本内容。
            if (JsonNode.Parse(originalDraft) is not JsonObject draft
                || draft["schema"]?.GetValue<string>() != "picotoo.storypack.v1"
                || draft["shots"] is not JsonArray shots)
            {
                return false;
            }

            var property = role + "_ref";
            var previous = draft[property]?.GetValue<string>();
            if (role != "style" && string.IsNullOrWhiteSpace(previous))
            {
                return false;
            }

            // 显式单镜覆盖若引用旧主资产，则一同更新；其他角色/场景保持原值。
            foreach (var item in shots)
            {
                if (item is not JsonObject shot)
                {
                    return false;
                }
                if (role == "scene" && shot["scene_ref"] is JsonValue scene
                    && string.Equals(scene.GetValue<string>(), previous, StringComparison.OrdinalIgnoreCase))
                {
                    shot["scene_ref"] = assetId;
                }
                if (role == "character" && shot["cast_refs"] is JsonArray cast)
                {
                    for (var index = 0; index < cast.Count; index++)
                    {
                        if (string.Equals(cast[index]?.GetValue<string>(), previous, StringComparison.OrdinalIgnoreCase))
                        {
                            cast[index] = assetId;
                        }
                    }
                }
            }

            draft[property] = assetId;
            var nextDraft = draft.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            if (nextDraft.Length > 100000 || Encoding.UTF8.GetByteCount(nextDraft) > 128 * 1024)
            {
                return false;
            }

            // 03. 绑定后原 Core 预览立即失效；必须重新明确点击预览。
            if (string.Equals(nextDraft, StoryPackJson, StringComparison.Ordinal))
            {
                Interlocked.Increment(ref _storyPackRevision);
                ResetPreparedGoal();
            }
            else
            {
                StoryPackJson = nextDraft;
            }
            StoryPackPreviewStatus = "已绑定登记素材；请重新只读检查。Owner 未批准，GPU 保持 HOLD。";
            return true;
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or ArgumentException)
        {
            // 无效草稿保持原样；已登记资产仍可通过同一文件幂等重试。
            return false;
        }
    }
}
