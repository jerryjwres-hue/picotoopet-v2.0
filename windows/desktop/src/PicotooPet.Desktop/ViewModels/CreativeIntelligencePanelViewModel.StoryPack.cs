using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>既有创意面板的可选只读 StoryPack 预览；不增加日常生产步骤或审批捷径。</summary>
public sealed partial class CreativeIntelligencePanelViewModel
{
    /// <summary>首片只读故事草稿：角色/厨房/风格资产 ID 仅是未登记的 draft ref，不是可信参考图。</summary>
    public const string MaotaiDinnerPilotDraft = """
        {
          "schema": "picotoo.storypack.v1",
          "episode_id": "maotai_dinner_p0_draft_v1",
          "title": "茅台的开饭仪式",
          "output_profile": "p0_landscape",
          "character_ref": "draft_maotai_identity_v1",
          "scene_ref": "draft_kitchen_layout_v1",
          "style_ref": "draft_cute3d_style_v1",
          "story": {
            "goal": "戴荧绿色三角围巾的阿拉斯加犬茅台，闻到晚餐香味，想立刻冲向食盆。",
            "payoff": "茅台克制偷吃的冲动，乖乖等待开饭信号，终于开心吃到第一口晚餐。"
          },
          "shots": [
            {
              "id": "S01",
              "action": "第一镜头4秒：可爱3D漫画风格，中景定场。毛茸茸的黑白奶油色阿拉斯加犬茅台戴荧绿色三角围巾，从画面左后方厨房门口走向右前方靠墙的银色双环圆口食盆。看到碗里的晚饭，他突然刹车，眼睛一亮，尾巴抬起。厨房门、墙、地面、食盆位置固定，不出现字幕或额外人物。",
              "state_in": "茅台站在厨房左后侧入口，双环圆口食盆在画面右前方靠墙。",
              "state_out": "茅台停在右侧双环圆口食盆前，鼻尖离碗一掌，双前爪着地。",
              "because": "他看见晚饭就在面前，忍不住想抢先开吃。"
            },
            {
              "id": "S02",
              "action": "第二镜头4秒：沿用相同厨房空间和食盆真实圆形双环口沿。茅台把鼻尖慢慢靠近食盆，眼看就要偷吃，突然想起还没听到开饭指令；他滑稽地后缩，端正坐好、双耳竖起，看向画外等待。荧绿色三角围巾、毛色纹路和双环碗保持一致。",
              "state_in": "茅台停在右侧双环圆口食盆前，鼻尖离碗一掌，双前爪着地。",
              "state_out": "茅台端正坐在食盆左侧，鼻尖离碗一掌，双耳竖起，望向画外。",
              "because": "他想吃却记得开饭前必须先坐好等待。",
              "depends_on": ["S01"],
              "handoff": "continuous"
            },
            {
              "id": "S03",
              "action": "第三镜头4秒：保持同一餐厅厨房布局、光照和圆形双环食盆。画外响起短促开饭提示音（仅音效，无新角色入镜）；茅台先抬头确认，再迫不及待低头吃下第一口，蓬松尾巴欢快摆动，最后停在满足的表情。不得变换脸型、围巾颜色、食盆形状或位置。",
              "state_in": "茅台端正坐在食盆左侧，鼻尖离碗一掌，双耳竖起，望向画外。",
              "state_out": "茅台正低头吃第一口晚餐，荧绿色三角围巾清晰可见，食盆未移动。",
              "because": "开饭提示音终于响起，等待得到回报。",
              "depends_on": ["S02"],
              "handoff": "continuous"
            }
          ]
        }
        """;

    /// <summary>用户主动一键载入试片剧本，只修改内存草稿；不自动发送、审批或放行 GPU。</summary>
    public void LoadMaotaiDinnerPilotDraft()
    {
        StoryPackJson = MaotaiDinnerPilotDraft;
        StoryPackPreviewStatus = "茅台三镜头示例已载入；角色、场景和风格资产均未验证。点击只读检查，不会生成任务。";
    }

    private string _storyPackJson = string.Empty;
    private string _storyPackPreviewStatus = "可选：粘贴导演生成的 StoryPack JSON，仅校验镜头与资产。";
    private bool _isStoryPackPreviewBusy;
    private long _storyPackRevision;
    private string? _goalDraftObjective;
    private string? _goalDraftDigest;
    private long _goalDraftRevision = -1;
    private string? _submittedGoalDigest;
    private bool _isStoryGoalBusy;
    private string _storyGoalStatus = "先执行只读 StoryPack 检查，才可主动创建标准本地 Goal。";

    /// <summary>仅保留当前内存中粘贴的草稿；不上传历史、日志或本地缓存。</summary>
    public string StoryPackJson
    {
        get => _storyPackJson;
        set
        {
            if (SetProperty(ref _storyPackJson, value ?? string.Empty))
            {
                Interlocked.Increment(ref _storyPackRevision);
                ResetPreparedGoal();
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

    /// <summary>新路径复用现有 Human Goal；只有有效最新预览和显式用户点击才可提交。</summary>
    public bool CanCreateStoryGoal =>
        !IsStoryPackPreviewBusy && !_isStoryGoalBusy && _goalDraftObjective is not null
        && _goalDraftDigest is not null && _goalDraftRevision == Volatile.Read(ref _storyPackRevision)
        && !string.Equals(_submittedGoalDigest, _goalDraftDigest, StringComparison.Ordinal);

    public string StoryGoalStatus
    {
        get => _storyGoalStatus;
        private set => SetProperty(ref _storyGoalStatus, value);
    }

    private void ResetPreparedGoal()
    {
        _goalDraftObjective = null;
        _goalDraftDigest = null;
        _goalDraftRevision = -1;
        StoryGoalStatus = "草稿未通过最新的标准 Goal 准入检查。";
        RaisePropertyChanged(nameof(CanCreateStoryGoal));
    }

    /// <summary>纯 JSON 类型与范围校验，拒绝任何伪造放行或不一致的预览摘要。</summary>
    public static bool TryGetCanonicalGoalIntake(
        JsonElement preview, out string objective, out string digest)
    {
        objective = string.Empty;
        digest = string.Empty;
        if (preview.ValueKind != JsonValueKind.Object
            || !HasBool(preview, "validated", true)
            || !HasBool(preview, "can_queue", false)
            || !preview.TryGetProperty("production_compilation", out var compilation)
            || !HasBool(compilation, "executable", false)
            || !preview.TryGetProperty("core23_compatibility", out var compatibility)
            || !HasBool(compatibility, "gpu_post_authorized", false)
            || !preview.TryGetProperty("owner_review_subject", out var owner)
            || !HasBool(owner, "owner_approved", false)
            || !preview.TryGetProperty("shot_count", out var shots)
            || !shots.TryGetInt32(out var shotCount) || shotCount != 3
            || !preview.TryGetProperty("output", out var output)
            || !output.TryGetProperty("width", out var width) || width.GetInt32() != 832
            || !output.TryGetProperty("height", out var height) || height.GetInt32() != 480
            || !output.TryGetProperty("fps", out var fps) || fps.GetInt32() != 24
            || !output.TryGetProperty("frames_per_shot", out var perShot) || perShot.GetInt32() != 97
            || !output.TryGetProperty("planned_frames", out var total) || total.GetInt32() != 291
            || !preview.TryGetProperty("storypack_sha256", out var sourceHash)
            || sourceHash.ValueKind != JsonValueKind.String
            || !preview.TryGetProperty("canonical_goal_intake", out var intake)
            || intake.ValueKind != JsonValueKind.Object
            || !HasBool(intake, "ready_for_user_submission", true)
            || !HasBool(intake, "requires_explicit_user_action", true)
            || !HasBool(intake, "local_video_preferred", true)
            || !HasBool(intake, "source_evidence_verified", false)
            || !HasBool(intake, "creative_package_approved", false)
            || !HasBool(intake, "production_plan_executable", false)
            || !HasBool(intake, "owner_approved", false)
            || !HasBool(intake, "gpu_post_authorized", false)
            || !StringFieldIs(intake, "contract", "picotoo.storypack.canonical-goal-intake.v1")
            || !StringFieldIs(intake, "goal_type", "video.creative")
            || !StringFieldIs(intake, "depth", "standard")
            || !intake.TryGetProperty("blocking_reasons", out var reasons)
            || reasons.ValueKind != JsonValueKind.Array || reasons.GetArrayLength() != 0
            || !intake.TryGetProperty("storypack_sha256", out var intakeHash)
            || intakeHash.ValueKind != JsonValueKind.String
            || !intake.TryGetProperty("objective", out var statement)
            || statement.ValueKind != JsonValueKind.String)
        {
            return false;
        }

        var hash = sourceHash.GetString();
        var candidate = statement.GetString();
        if (hash is null || hash.Length != 64 || hash.Any(c => !(
            c is >= '0' and <= '9' or >= 'a' and <= 'f'))
            || !string.Equals(hash, intakeHash.GetString(), StringComparison.Ordinal)
            || candidate is null || candidate.Length is < 4 or > 2000
            || !candidate.Contains("纯宠物视频", StringComparison.Ordinal)
            || !candidate.Contains("3个镜头", StringComparison.Ordinal)
            || !candidate.Contains("每个镜头4秒", StringComparison.Ordinal)
            || !intake.TryGetProperty("objective_character_count", out var length)
            || !length.TryGetInt32(out var reportedLength) || reportedLength != candidate.Length)
        {
            return false;
        }

        objective = candidate;
        digest = hash;
        return true;
    }

    private static bool StringFieldIs(JsonElement json, string property, string expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(property, out var value)
        && value.ValueKind == JsonValueKind.String
        && string.Equals(value.GetString(), expected, StringComparison.Ordinal);

    /// <summary>只在用户确认时创建现有 Core HumanGoal；重复操作按 StoryPack 摘要幂等。</summary>
    public async Task CreateStoryGoalAsync(CancellationToken cancellationToken)
    {
        if (!CanCreateStoryGoal)
        {
            return;
        }

        var revision = Volatile.Read(ref _storyPackRevision);
        var objective = _goalDraftObjective!;
        var digest = _goalDraftDigest!;
        _isStoryGoalBusy = true;
        RaisePropertyChanged(nameof(CanCreateStoryGoal));
        StoryGoalStatus = "正在向 Mac Core 提交现有 video.creative Goal；不会创建 GPU 任务……";
        try
        {
            var created = await RequireSession().CreateGoalAsync(
                new HumanGoalCreateRequest("video.creative", objective, "standard"),
                "studio-storypack-goal-v1-" + digest,
                cancellationToken);
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                _submittedGoalDigest = digest;
                StoryGoalStatus = "本地创意 Goal 已创建：" + created.GoalId
                    + "。需通过来源核验、Creative 和 Owner 门禁；GPU 仍 HOLD。";
            }
        }
        catch (ApiException)
        {
            if (Volatile.Read(ref _storyPackRevision) == revision)
            {
                StoryGoalStatus = "标准 Goal 创建失败，未获得任何生产或 GPU 授权；可重试。";
            }
        }
        finally
        {
            _isStoryGoalBusy = false;
            RaisePropertyChanged(nameof(CanCreateStoryGoal));
        }
    }

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

        ResetPreparedGoal();
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
                if (!StoryPackPreviewStatus.Contains("UNVERIFIED", StringComparison.Ordinal)
                    && TryGetCanonicalGoalIntake(result, out var objective, out var digest))
                {
                    _goalDraftObjective = objective;
                    _goalDraftDigest = digest;
                    _goalDraftRevision = revision;
                    StoryGoalStatus = "已核验：可主动创建现有 Mac 本地 video.creative Goal。"
                        + " 这只是创意研究入口，资产、Owner、GPU 均未批准。";
                    RaisePropertyChanged(nameof(CanCreateStoryGoal));
                }
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
            || !fps.TryGetInt32(out var framesPerSecond)
            || !output.TryGetProperty("frames_per_shot", out var perShotFrames)
            || !perShotFrames.TryGetInt32(out var renderFrames)
            || !output.TryGetProperty("planned_frames", out var totalFrames)
            || !totalFrames.TryGetInt32(out var renderTotal)
            || shotCount is < 1 or > 30
            || renderFrames is < 1 or > 121
            || renderTotal != (long)shotCount * renderFrames)
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

        // 四秒是镜头的目标时长；Wan 使用 4n+1 帧族，四秒对应 97 渲染帧。
        return $"剧本结构：{shotCount} 镜头 · 目标 {seconds} 秒 · {pixelsWide}×{pixelsHigh} · {framesPerSecond}fps。"
            + $" 每镜 {renderFrames} 帧，共 {renderTotal} 渲染帧。"
            + $" 未验证资产 {unverified} 项。Owner 未批准，GPU HOLD；不可生成或发布。";
    }

    private static bool HasBool(JsonElement json, string property, bool expected) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(property, out var value)
        && value.ValueKind == (expected ? JsonValueKind.True : JsonValueKind.False);
}
