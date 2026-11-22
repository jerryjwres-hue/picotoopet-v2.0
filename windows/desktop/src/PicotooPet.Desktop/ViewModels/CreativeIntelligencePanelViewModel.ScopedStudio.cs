using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>同一工作台内的动态示例与当前草稿提交锁；只修改草稿，不自动生成。</summary>
public sealed partial class CreativeIntelligencePanelViewModel
{
    public void LoadDynamicDinnerPilotDraft()
    {
        // 01. 旧示例保留；新示例明确使用已支持的三个主动作。
        const string draft = """
        {
          "schema": "picotoo.storypack.v1",
          "episode_id": "maotai_dynamic_feeding_p0",
          "title": "茅台的晚餐",
          "output_profile": "p0_landscape",
          "character_ref": "draft_maotai_identity_v1",
          "scene_ref": "draft_kitchen_layout_v1",
          "style_ref": "draft_cute3d_style_v1",
          "story": {
            "goal": "茅台发现晚餐，走到食盆旁。",
            "payoff": "茅台低头吃到第一口晚餐。"
          },
          "shots": [
            {
              "id": "S01",
              "action": "茅台原地站立，转移视线发现食盆。",
              "state_in": "茅台在厨房门口站立，尚未望向食盆。",
              "state_out": "茅台在厨房门口站立，望向食盆。",
              "because": "食盆里的晚餐吸引了注意。"
            },
            {
              "id": "S02",
              "action": "茅台从左向右走向固定食盆。",
              "state_in": "茅台在厨房门口站立，望向食盆。",
              "state_out": "茅台站在食盆旁，尚未进食。",
              "because": "他想吃到晚餐。",
              "depends_on": ["S01"],
              "handoff": "continuous"
            },
            {
              "id": "S03",
              "action": "茅台低头吃下第一口。",
              "state_in": "茅台站在食盆旁，尚未进食。",
              "state_out": "茅台站在食盆旁低头进食。",
              "because": "他已经来到晚餐前。",
              "depends_on": ["S02"],
              "handoff": "continuous"
            }
          ],
          "dynamic_motion": {
            "policy": "dynamic-pet-feeding-v1.0.0",
            "start_location": "the kitchen doorway",
            "bowl_location": "the right dining corner",
            "support_surface": "wood floor",
            "bowl_description": "round double-rim steel food bowl",
            "screen_direction": "LEFT_TO_RIGHT",
            "shots": [
              {"shot_id":"S01","event":"NOTICE_BOWL","framing":"wide full-body shot"},
              {"shot_id":"S02","event":"APPROACH_BOWL","framing":"medium full-body shot"},
              {"shot_id":"S03","event":"BEGIN_EATING","framing":"close shot of muzzle and bowl"}
            ]
          }
        }
        """;
        if (_isStoryGoalBusy || _isAssetImportBusy || IsStoryPackPreviewBusy)
        {
            return;
        }
        // Reuse selected draft role IDs, if present, rather than forcing repeated imports.
        var next = JsonNode.Parse(draft)!.AsObject();
        try
        {
            if (JsonNode.Parse(StoryPackJson) is JsonObject existing)
            {
                foreach (var property in new[] { "character_ref", "scene_ref", "style_ref" })
                {
                    if (existing[property] is JsonValue value && value.TryGetValue<string>(out var id)
                        && id is { Length: 70 } && id.StartsWith("asset-", StringComparison.Ordinal))
                    {
                        next[property] = id;
                    }
                }
            }
        }
        catch (JsonException)
        {
            // Invalid existing draft cannot supply a verified reference.
        }
        StoryPackJson = next.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
        StoryPackPreviewStatus = "已载入动态三镜示例；确认实际空间和素材后再提交，不生成视频。";
    }

    // 02. 冻结旧的普通 Goal 按钮；网络期间不得重复提交或复用旧预览。
    public bool TryBeginScopedStorySubmission(string originalDraft)
    {
        if (_isAssetImportBusy || IsStoryPackPreviewBusy || _isStoryGoalBusy
            || !string.Equals(originalDraft, StoryPackJson, StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(originalDraft))
        {
            return false;
        }
        _isStoryGoalBusy = true;
        Interlocked.Increment(ref _storyPackRevision);
        ResetPreparedGoal();
        RaisePropertyChanged(nameof(CanPreviewStoryPack));
        RaisePropertyChanged(nameof(CanCreateStoryGoal));
        StoryGoalStatus = "正在核验动态剧本与已登记声明；不会启动 GPU。";
        return true;
    }

    public void EndScopedStorySubmission(string message)
    {
        _isStoryGoalBusy = false;
        StoryGoalStatus = message;
        RaisePropertyChanged(nameof(CanPreviewStoryPack));
        RaisePropertyChanged(nameof(CanCreateStoryGoal));
    }
}
