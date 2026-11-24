using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.ViewModels;
using WpfButton = System.Windows.Controls.Button;
using WpfMessageBox = System.Windows.MessageBox;

namespace PicotooPet.Desktop.Views;

/// <summary>明确同意后通过原 Core 通道登记本地素材；不启动预览、Goal 或渲染。</summary>
public partial class FilmStudioAssetPanel : System.Windows.Controls.UserControl
{
    // 固定动态三镜事件序列，复用数组避免重复分配。
    private static readonly string[] DynamicEvents = ["NOTICE_BOWL", "APPROACH_BOWL", "BEGIN_EATING"];

    public FilmStudioAssetPanel()
    {
        InitializeComponent();
    }

    private void Project_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        // 01. 必须选择真实活动项目，不以默认目录或草稿推测项目 ID。
        if (ImportCharacterButton is null || ImportSceneButton is null || ImportStyleButton is null)
        {
            return;
        }
        var selected = AssetProjectSelector.SelectedItem is ProjectRecord { Status: "Active" };
        ImportCharacterButton.IsEnabled = selected;
        ImportSceneButton.IsEnabled = selected;
        ImportStyleButton.IsEnabled = selected;
        RegisterLoraButton.IsEnabled = selected;
        if (SubmitScopedStoryButton is not null)
        {
            SubmitScopedStoryButton.IsEnabled = selected;
        }
    }

    private void LoadDynamicPilot_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is FilmStudioPageViewModel model && AssetControls.IsEnabled)
        {
            model.Creative.LoadDynamicDinnerPilotDraft();
            if (string.IsNullOrWhiteSpace(ScopedSubjectInput.Text))
            {
                ScopedSubjectInput.Text = "pet:maotai";
            }
        }
    }

    private async void SubmitScopedStory_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not FilmStudioPageViewModel model
            || AssetProjectSelector.SelectedItem is not ProjectRecord { Status: "Active" } project
            || !AssetControls.IsEnabled)
        {
            return;
        }

        var draft = model.Creative.StoryPackJson;
        var subject = ScopedSubjectInput.Text.Trim();
        if (!model.Creative.TryBeginScopedStorySubmission(draft))
        {
            AssetStatus.Text = "请先载入动态剧本，且避免与其他创意操作同时运行。";
            return;
        }

        AssetControls.IsEnabled = false;
        var status = "未获有效回执，未进入生产；可安全重试同一剧本与声明。";
        try
        {
            // 01. 对当前草稿重新进行真实 Core 校验；旧预览和普通 Goal 不可复用。
            var pack = JsonElement.Parse(draft);
            var session = model.ScopedSession;
            var preview = await session.PreviewStudioStoryPackAsync(pack, CancellationToken.None);
            var scope = ParseScopedPreview(pack, preview);
            var existingResponse = await session.GetScopedOwnerPacketsAsync(
                project.ProjectId, scope.CharacterRef, subject, scope.CharacterSha, CancellationToken.None);
            var packets = existingResponse.GetProperty("packets");

            // 02. 复用最新匹配候选时必须展示实际声明并确认；没有候选则由用户首次填写。
            JsonElement claims;
            JsonElement? newPacket = null;
            string packetDigest;
            if (ReuseOwnerPacket.IsChecked == true && packets.GetArrayLength() > 0)
            {
                var candidate = packets[0];
                claims = candidate.GetProperty("claims");
                packetDigest = candidate.GetProperty("packet_digest").GetString()!;
            }
            else
            {
                claims = JsonSerializer.SerializeToElement(new[]
                {
                    new { kind = "visible_identity", statement = OwnerIdentityInput.Text.Trim() },
                    new { kind = "visible_scene", statement = OwnerSceneInput.Text.Trim() },
                    new { kind = "creative_intent", statement = OwnerIntentInput.Text.Trim() },
                });
                newPacket = JsonSerializer.SerializeToElement(new
                {
                    subject_key = subject, photo_sha256_claim = scope.CharacterSha, claims,
                });
                packetDigest = await session.PreviewOwnerPacketAsync(
                    newPacket.Value, CancellationToken.None);
            }

            if (!string.Equals(draft, model.Creative.StoryPackJson, StringComparison.Ordinal))
            {
                status = "草稿已改变，未提交；请重新核验。";
                return;
            }

            var claimSummary = string.Join("\n", claims.EnumerateArray().Select(item =>
                item.GetProperty("kind").GetString() + "：" + item.GetProperty("statement").GetString()));
            var answer = WpfMessageBox.Show(
                Window.GetWindow(this),
                $"项目：{project.Title}\n宠物：{subject}\n角色字节 SHA256：{scope.CharacterSha}\n\n"
                + claimSummary + "\n\n本次确定的动态动作：\n" + scope.MotionSummary
                + "\n\n确认上述真实声明与本次剧本范围？仅登记声明并创建本地创意 Goal；"
                + "正式主人结构化审核、关键帧批准及 GPU HOLD 仍独立有效。",
                "确认动态创意范围",
                MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
            if (answer != MessageBoxResult.Yes)
            {
                status = "已取消；未创建 Goal 或新声明。";
                return;
            }

            // 03. 同一冻结草稿和已明确查看的声明。写入中若草稿变化，停止后续提交。
            if (newPacket.HasValue)
            {
                await session.CommitReviewedOwnerPacketAsync(
                    newPacket.Value, packetDigest, CancellationToken.None);
            }
            if (!string.Equals(draft, model.Creative.StoryPackJson, StringComparison.Ordinal))
            {
                status = "草稿已改变；若新声明已登记则保留，未创建 Goal。";
                return;
            }
            var id = await session.SubmitScopedStoryGoalAsync(
                pack, project.ProjectId, scope.CharacterRef, scope.CharacterSha, subject,
                packetDigest, scope.SubjectDigest, scope.StoryDigest, scope.MotionDigest,
                CancellationToken.None);
            status = "已创建/复用本地动态创意 Goal：" + id
                + "。下一步在 Mac 完成正式主人结构化审核；GPU 未放行。";
        }
        catch (ArgumentException)
        {
            status = "请检查宠物身份键、素材和三类声明（每条10–500字符）。未获有效提交回执。";
        }
        catch (Exception)
        {
            // 只展示稳定提示，避免回显原始私有声明、设备凭据或文件路径。
            status = "未获可验证提交回执；检查 Core 连接、现有素材和证据范围后原样重试。GPU 未放行。";
        }
        finally
        {
            AssetStatus.Text = status;
            model.Creative.EndScopedStorySubmission(status);
            AssetControls.IsEnabled = true;
        }
    }

    public sealed record ScopedPreview(
        string CharacterRef, string CharacterSha, string StoryDigest,
        string SubjectDigest, string MotionDigest, string MotionSummary);

    public static ScopedPreview ParseScopedPreview(JsonElement draft, JsonElement preview)
    {
        // 服务端必须确认每一份实际角色/场景/风格字节；任何未批准字段缺失都拒绝。
        if (CreativeIntelligencePanelViewModel.FormatReadOnlyStoryPackPreview(preview)
            .Contains("UNVERIFIED", StringComparison.Ordinal)
            || !preview.TryGetProperty("dynamic_motion_proposal", out var motion)
            || !IsString(motion, "policy", "dynamic-pet-feeding-v1.0.0")
            || !IsString(motion, "status", "DYNAMIC_PROPOSAL_REQUIRES_OWNER_REVIEW")
            || motion.GetProperty("owner_approved").ValueKind != JsonValueKind.False
            || motion.GetProperty("can_queue").ValueKind != JsonValueKind.False
            || motion.GetProperty("gpu_post_authorized").ValueKind != JsonValueKind.False)
        {
            throw new InvalidOperationException("未获得有效动态动作提案。");
        }
        var owner = preview.GetProperty("owner_review_subject");
        if (!IsString(owner, "status", "REVIEW_SUBJECT_PREPARED_UNAPPROVED")
            || owner.GetProperty("can_queue").ValueKind != JsonValueKind.False)
        {
            throw new InvalidOperationException("未获得完整素材审核主体。");
        }
        var storyDigest = ReadDigest(preview, "storypack_sha256");
        var subjectDigest = ReadDigest(owner, "subject_sha256");
        var motionDigest = ReadDigest(motion, "motion_digest");
        if (!IsString(motion, "storypack_sha256", storyDigest))
        {
            throw new InvalidOperationException("动态动作与剧本不匹配。");
        }
        var checks = preview.GetProperty("asset_record_checks").EnumerateArray().ToArray();
        if (checks.Length != 3)
        {
            throw new InvalidOperationException("只支持三个固定角色/场景/风格素材。");
        }
        var characterRef = draft.GetProperty("character_ref").GetString()!;
        var characterSha = string.Empty;
        foreach (var role in new[] { "character", "scene", "style" })
        {
            var id = draft.GetProperty(role + "_ref").GetString()!;
            var match = checks.SingleOrDefault(item => IsString(item, "ref", id));
            if (match.ValueKind != JsonValueKind.Object
                || !IsString(match, "artifact_type", "storypack_" + role)
                || !IsString(match, "managed_object_integrity", "CONTENT_VERIFIED_UNAPPROVED")
                || match.GetProperty("content_integrity_verified").ValueKind != JsonValueKind.True
                || match.GetProperty("owner_approval_verified").ValueKind != JsonValueKind.False
                || match.GetProperty("usable_for_generation").ValueKind != JsonValueKind.False)
            {
                throw new InvalidOperationException("存在未验证或错误角色素材。");
            }
            var sha = ReadDigest(match, "recorded_sha256");
            if (role == "character")
            {
                characterSha = sha;
            }
        }
        var shots = motion.GetProperty("shots").EnumerateArray().ToArray();
        if (shots.Length != 3 || !shots.Select(shot => shot.GetProperty("event").GetString()).SequenceEqual(
            DynamicEvents))
        {
            throw new InvalidOperationException("不支持的动态故事动作序列。");
        }
        var motionSummary = string.Join("\n", shots.Select(shot =>
            shot.GetProperty("shot_id").GetString() + " · " + shot.GetProperty("visible_action").GetString()
            + "\n" + shot.GetProperty("opening_state").GetString()
            + " → " + shot.GetProperty("closing_state").GetString()));
        return new ScopedPreview(characterRef, characterSha, storyDigest, subjectDigest, motionDigest, motionSummary);
    }

    private static bool IsString(JsonElement element, string property, string expected) =>
        element.ValueKind == JsonValueKind.Object
        && element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
        && string.Equals(value.GetString(), expected, StringComparison.Ordinal);

    private static string ReadDigest(JsonElement element, string property)
    {
        var value = element.GetProperty(property).GetString();
        if (value is not { Length: 64 } || value.Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')))
        {
            throw new InvalidOperationException("摘要缺失。");
        }
        return value;
    }

    private async void RefreshProjects_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not FilmStudioPageViewModel model || !AssetControls.IsEnabled)
        {
            return;
        }

        AssetControls.IsEnabled = false;
        try
        {
            var selectedId = (AssetProjectSelector.SelectedItem as ProjectRecord)?.ProjectId;
            var projects = await model.GetAssetProjectsAsync(CancellationToken.None);
            AssetProjectSelector.ItemsSource = projects;
            AssetProjectSelector.SelectedItem = projects.FirstOrDefault(p => p.ProjectId == selectedId);
            AssetStatus.Text = projects.Count == 0
                ? "没有活动项目；请先在高级 → 项目创建。"
                : $"已读取 {projects.Count} 个活动项目，请选择一个。";
        }
        catch (Exception)
        {
            AssetProjectSelector.ItemsSource = null;
            AssetStatus.Text = "未能读取项目，请检查 Core 连接后重试。";
        }
        finally
        {
            AssetControls.IsEnabled = true;
        }
    }

    private async void ImportAsset_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not FilmStudioPageViewModel model
            || AssetProjectSelector.SelectedItem is not ProjectRecord { Status: "Active" } project
            || sender is not WpfButton { Tag: string role }
            || role is not ("character" or "scene" or "style")
            || !AssetControls.IsEnabled)
        {
            return;
        }

        var originalDraft = model.Creative.StoryPackJson;
        if (string.IsNullOrWhiteSpace(originalDraft))
        {
            AssetStatus.Text = "请先在下方载入示例或打开自己的 StoryPack JSON，再选择素材。";
            return;
        }

        // 02. 原生文件选择器只读用户选中的单一文件；不扫描目录。
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Filter = role == "style"
                ? "风格文件|*.png;*.jpg;*.jpeg;*.webp;*.txt;*.md;*.json"
                : "图片文件|*.png;*.jpg;*.jpeg;*.webp",
            CheckFileExists = true,
            Multiselect = false,
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }

        AssetControls.IsEnabled = false;
        var importStarted = false;
        try
        {
            var mediaType = Path.GetExtension(dialog.FileName).ToUpperInvariant() switch
            {
                ".PNG" => "image/png",
                ".JPG" or ".JPEG" => "image/jpeg",
                ".WEBP" => "image/webp",
                ".TXT" or ".MD" when role == "style" => "text/plain",
                ".JSON" when role == "style" => "application/json",
                _ => throw new InvalidDataException("Unsupported asset extension"),
            };

            byte[] data;
            using (var stream = new FileStream(
                dialog.FileName, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (stream.Length is <= 0 or > MacCoreClient.MaxStudioAssetBytes)
                {
                    throw new InvalidDataException("Asset size");
                }
                data = new byte[(int)stream.Length];
                await stream.ReadExactlyAsync(data);
                if (stream.ReadByte() != -1)
                {
                    throw new InvalidDataException("Asset changed");
                }
            }

            // 03. 核对本次文件、项目与角色，并要求单次明确同意；默认拒绝。
            var roleLabel = role switch { "character" => "角色", "scene" => "场景", _ => "风格" };
            var answer = WpfMessageBox.Show(
                Window.GetWindow(this),
                $"项目：{project.Title}\n素材：{Path.GetFileName(dialog.FileName)}\n类型：{roleLabel}\n大小：{data.Length:N0} 字节\n\n将副本登记到配对 Mac Core？不移动原文件，不通过 Owner / MASTER，不创建任务或解除 GPU HOLD。",
                "确认本地素材登记",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question,
                MessageBoxResult.No);

            if (answer != MessageBoxResult.Yes)
            {
                AssetStatus.Text = "已取消，未发送素材。";
                return;
            }

            // 04. 回执由客户端独立校验；绑定只更新当前相同草稿，绝不自动提交。
            if (!model.Creative.TryBeginAssetImport(originalDraft))
            {
                AssetStatus.Text = "草稿已改变或创意操作进行中；未发送素材，请重试。";
                return;
            }
            importStarted = true;
            AssetStatus.Text = "正在核验并登记本地素材副本……";
            var id = await model.RegisterAssetAsync(
                project.ProjectId, role, mediaType, data, CancellationToken.None);

            var bound = model.Creative.TryBindImportedAsset(originalDraft, role, id);
            AssetStatus.Text = bound
                ? $"{roleLabel}已登记并绑定。请重新点击只读检查；Owner 未批准，GPU HOLD。\n{id}"
                : $"{roleLabel}已登记，但草稿已变化或无法绑定；未覆盖草稿。再次选择同一文件可幂等重试。\n{id}";
            if (bound)
            {
                // 05. 登记完成仍未批准。必须第二次明确确认，才请求
                //     现有审批中心创建 Pending；不自动点击 Owner 批准。
                var digest = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(data));
                var approval = await OfferOwnerApprovalRequestAsync(
                    model, roleLabel, id, digest, null);
                if (!string.IsNullOrWhiteSpace(approval))
                {
                    AssetStatus.Text = approval;
                }
            }
        }
        catch (Exception)
        {
            // 网络失败也可能是登记成功但回执丢失；不作成功/未写入断言。
            AssetStatus.Text = "登记未获可验证回执；请确认连接、素材不超过 16 MiB 后重试原文件。未自动绑定或授权生产。";
        }
        finally
        {
            if (importStarted)
            {
                model.Creative.EndAssetImport();
            }
            AssetControls.IsEnabled = true;
        }
    }
}
