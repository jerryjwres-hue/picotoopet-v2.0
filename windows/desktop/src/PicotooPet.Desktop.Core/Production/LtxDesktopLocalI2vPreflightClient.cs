using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>现有 LTX Desktop 1.3.1 Remote 本地协议的单镜候选；不是 Core 授权或 GPU 作业。</summary>
public sealed record LtxDesktopI2vDraft(
    string ShotId,
    string SourceStoryPackSha256,
    string SourceOutputProfile,
    string FirstFrameFile,
    string FirstFrameSha256,
    string Prompt,
    int Seed);

/// <summary>只读原生能力验收；上传 assetId、Owner approval 和执行 Lane 仍然缺失。</summary>
public sealed record LtxDesktopReadiness(
    string FirstFrameSha256,
    string SourceStoryPackSha256,
    string SourceOutputProfile,
    JsonObject VendorSubmissionTemplate,
    bool BytesLocallyVerified,
    bool LocalSettingsVerified,
    bool ModelCapabilityVerified,
    bool QueueIdleVerified,
    bool DuplicateHistoryAbsent,
    bool VendorAssetUploaded,
    bool GenerationLaneVerified,
    bool OwnerApproved,
    bool CanSubmit,
    int GpuPost);

/// <summary>
/// 复用本机 LTX Desktop Remote：只允许 127.0.0.1:41955 的 GET；
/// 实际 POST 仍须接入 Core 已签名 Worker Attempt、持久提交日志及 GPU Lease。
/// </summary>
public sealed class LtxDesktopLocalI2vPreflightClient : IAsyncDisposable
{
    public static readonly Uri FixedBaseAddress =
        new("http://127.0.0.1:41955/", UriKind.Absolute);

    private const int MaxJsonBytes = 2 * 1024 * 1024;
    private const long MaxFirstFrameBytes = 32 * 1024 * 1024;
    private readonly HttpClient _http;
    private readonly bool _ownsClient;

    public LtxDesktopLocalI2vPreflightClient(HttpClient http)
    {
        _http = http ?? throw new ArgumentNullException(nameof(http));
        _ownsClient = false;
        VerifyFixedLocalEndpoint(http);
    }

    private LtxDesktopLocalI2vPreflightClient(HttpClient http, bool ownsClient)
        : this(http) => _ownsClient = ownsClient;

    public static LtxDesktopLocalI2vPreflightClient Create(string pairedBearerToken)
    {
        // 01. 由现有 Windows DPAPI 会话读取令牌后传入内存。永不保存在
        //     Workflow、日志或 Core 任务；禁止代理及任意云端重定向。
        if (string.IsNullOrWhiteSpace(pairedBearerToken))
        {
            throw new InvalidOperationException("LTX_DESKTOP_PAIRING_REQUIRED");
        }
        var handler = new SocketsHttpHandler
        {
            UseProxy = false,
            AllowAutoRedirect = false,
            ConnectTimeout = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer = 1,
        };
        var http = new HttpClient(handler, disposeHandler: true)
        {
            BaseAddress = FixedBaseAddress,
            Timeout = TimeSpan.FromSeconds(15),
        };
        http.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", pairedBearerToken);
        return new LtxDesktopLocalI2vPreflightClient(http, ownsClient: true);
    }

    /// <summary>仅 GET 本地接口并读取本机设置；绝不上传首帧、创建新任务或消费 GPU。</summary>
    public async Task<LtxDesktopReadiness> PreflightAsync(
        LtxDesktopI2vDraft draft, string localSettingsFile,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(draft);
        // 02. 11-21 横屏 StoryPack 不得悄悄切换成竖屏 LTX 任务。
        //     必须明确选用独立的 portrait 版本再进入本地 I2V。
        if (draft.ShotId is not ("S01" or "S02" or "S03")
            || !IsSha(draft.SourceStoryPackSha256) || !IsSha(draft.FirstFrameSha256)
            || draft.SourceOutputProfile != "design_portrait"
            || draft.Seed < 0
            || string.IsNullOrWhiteSpace(draft.Prompt)
            || draft.Prompt.Length > 10_000)
        {
            throw new InvalidOperationException("LTX_DESKTOP_DRAFT_OR_PROFILE_UNVERIFIED");
        }

        // 03. 这里没有直接调用图片生成器。只核验实际的已选首帧，
        //     不把 C8B 角色母版或 LoRA 权重误认为 I2V 已接受的首帧。
        var framePath = Path.GetFullPath(draft.FirstFrameFile);
        var info = new FileInfo(framePath);
        if (!info.Exists || info.Length is <= 0 or > MaxFirstFrameBytes
            || (info.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("LTX_DESKTOP_FIRST_FRAME_INVALID");
        }
        await using (var source = new FileStream(
            framePath, FileMode.Open, FileAccess.Read, FileShare.Read,
            1024 * 1024, FileOptions.SequentialScan))
        {
            var sha = Convert.ToHexStringLower(
                await SHA256.HashDataAsync(source, cancellationToken).ConfigureAwait(false));
            if (sha != draft.FirstFrameSha256 || source.Length != info.Length)
            {
                throw new InvalidOperationException("LTX_DESKTOP_FIRST_FRAME_SHA_MISMATCH");
            }
        }

        // 04. 完全沿用已核实的本机 LTX Desktop Settings 两个 local-only
        //     选择；可选增强不表示 Owner 审核过的提示词被改动。
        var settingsInfo = new FileInfo(localSettingsFile);
        if (!settingsInfo.Exists || settingsInfo.Length is <= 0 or > 64 * 1024
            || (settingsInfo.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("LTX_DESKTOP_LOCAL_SETTINGS_UNAVAILABLE");
        }
        var settings = JsonNode.Parse(await File.ReadAllTextAsync(
            settingsInfo.FullName, cancellationToken).ConfigureAwait(false)) as JsonObject
            ?? throw new InvalidDataException("LTX_DESKTOP_SETTINGS_JSON_INVALID");
        if (settings["user_prefers_ltx_api_video_generations"] is not JsonValue paid
            || !paid.TryGetValue<bool>(out var paidSelected)
            || paidSelected
            || settings["use_local_text_encoder"] is not JsonValue local
            || !local.TryGetValue<bool>(out var textIsLocal)
            || !textIsLocal)
        {
            throw new InvalidOperationException("LTX_DESKTOP_LOCAL_ONLY_NOT_VERIFIED");
        }

        // 05. 所有 REST 读取均限定到本机 loopback；任何忙队列、
        //     版本不支持或已有重复任务都在下载/上传前拒绝。
        var session = await GetAsync("api/session", cancellationToken).ConfigureAwait(false);
        if (session.Count == 0)
        {
            throw new InvalidDataException("LTX_DESKTOP_SESSION_INVALID");
        }
        var queue = await GetAsync("api/generation-queue", cancellationToken)
            .ConfigureAwait(false);
        if (!queue.ContainsKey("active") || queue["queued"] is not JsonArray queued)
        {
            throw new InvalidDataException("LTX_DESKTOP_QUEUE_SCHEMA_UNVERIFIED");
        }
        if (queue["active"] is not null || queued.Count > 0)
        {
            throw new InvalidOperationException("LTX_DESKTOP_QUEUE_BUSY");
        }

        var models = await GetAsync("api/generate/models-specs", cancellationToken)
            .ConfigureAwait(false);
        var downloads = models["downloaded_local_models"] as JsonArray
            ?? throw new InvalidDataException("LTX_DESKTOP_LOCAL_MODELS_UNVERIFIED");
        var installed = downloads.OfType<JsonObject>().FirstOrDefault(
            item => item["model"]?.GetValue<string>() == "ltx-2.5-fast");
        var profile = installed?["spec"]?["supported_resolutions_durations"]?["720p"];
        if (profile is null
            || !(profile["aspect_ratios"] as JsonArray ?? [])
                .Any(item => item?.GetValue<string>() == "9:16")
            || !(profile["fps_to_durations"]?["24"] as JsonArray ?? [])
                .Any(item => item is JsonValue value
                             && value.TryGetValue<int>(out var seconds)
                             && seconds == 4))
        {
            throw new InvalidOperationException("LTX_DESKTOP_LOCAL_4S_MODEL_UNSUPPORTED");
        }

        // 06. 历史去重必须考虑 Prompt + Model + Ratio + Duration +
        //     fps + seed。旧客户端只有 8s/null seed，不能替代 4s 验收。
        var history = await GetArrayAsync(
            "api/generations?feature=image-to-video", cancellationToken)
            .ConfigureAwait(false);
        // 07. PowerShell may expose a nested returned array; flatten a
        //     single array level, but do not silently ignore unknown records.
        var records = new List<JsonObject>();
        foreach (var item in history)
        {
            if (item is JsonObject one)
            {
                records.Add(one);
            }
            else if (item is JsonArray inner)
            {
                if (inner.Any(child => child is not JsonObject))
                {
                    throw new InvalidDataException("LTX_DESKTOP_HISTORY_SCHEMA_INVALID");
                }
                records.AddRange(inner.OfType<JsonObject>());
            }
            else
            {
                throw new InvalidDataException("LTX_DESKTOP_HISTORY_SCHEMA_INVALID");
            }
        }
        var duplicated = records.Any(item =>
        {
            var p = item["spec"]?["params"];
            return p?["prompt"]?.GetValue<string>() == draft.Prompt
                   && p?["model"]?.GetValue<string>() == "ltx-2.5-fast"
                   && p?["resolution"]?.GetValue<string>() == "720p"
                   && p?["aspectRatio"]?.GetValue<string>() == "9:16"
                   && p?["duration"]?.GetValue<int>() == 4
                   && p?["fps"]?.GetValue<int>() == 24
                   && p?["seed"]?.GetValue<int>() == draft.Seed;
        });
        if (duplicated)
        {
            throw new InvalidOperationException("LTX_DESKTOP_MATCHING_HISTORY_EXISTS");
        }

        // 07. 标准请求仅是不可提交的模板：startFrame.assetId 为 null，
        //     需要后续正式 Worker Attempt 的受控上传返回值才能填入。
        var template = new JsonObject
        {
            ["params"] = new JsonObject
            {
                ["prompt"] = draft.Prompt,
                ["model"] = "ltx-2.5-fast",
                ["resolution"] = "720p",
                ["aspectRatio"] = "9:16",
                ["duration"] = 4,
                ["fps"] = 24,
                ["seed"] = draft.Seed,
                ["cameraMotion"] = "none",
                ["negativePrompt"] = "",
                ["promptProvenance"] = "typed",
            },
            ["inputs"] = new JsonObject
            {
                ["startFrame"] = new JsonObject { ["assetId"] = null },
            },
            ["contract_version"] = 1,
        };
        return new LtxDesktopReadiness(
            draft.FirstFrameSha256, draft.SourceStoryPackSha256,
            draft.SourceOutputProfile, template, true, true, true, true, true,
            VendorAssetUploaded: false, GenerationLaneVerified: false,
            OwnerApproved: false, CanSubmit: false, GpuPost: 0);
    }

    private async Task<JsonObject> GetAsync(string path, CancellationToken ct)
    {
        using var message = new HttpRequestMessage(HttpMethod.Get, path);
        using var response = await _http.SendAsync(message,
            HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException("LTX_DESKTOP_HTTP_" + (int)response.StatusCode);
        }
        var length = response.Content.Headers.ContentLength;
        if (length.HasValue && length.Value > MaxJsonBytes)
        {
            throw new InvalidDataException("LTX_DESKTOP_REPLY_TOO_LARGE");
        }
        var bytes = await response.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (bytes.Length is <= 0 or > MaxJsonBytes)
        {
            throw new InvalidDataException("LTX_DESKTOP_REPLY_TOO_LARGE");
        }
        return JsonNode.Parse(bytes) as JsonObject
            ?? throw new InvalidDataException("LTX_DESKTOP_REPLY_JSON_INVALID");
    }

    private async Task<JsonArray> GetArrayAsync(string path, CancellationToken ct)
    {
        using var message = new HttpRequestMessage(HttpMethod.Get, path);
        using var response = await _http.SendAsync(message,
            HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException("LTX_DESKTOP_HTTP_" + (int)response.StatusCode);
        }
        var bytes = await response.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (bytes.Length is <= 0 or > MaxJsonBytes)
        {
            throw new InvalidDataException("LTX_DESKTOP_REPLY_TOO_LARGE");
        }
        return JsonNode.Parse(bytes) as JsonArray
            ?? throw new InvalidDataException("LTX_DESKTOP_HISTORY_SCHEMA_INVALID");
    }

    private static bool IsSha(string? value) =>
        value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void VerifyFixedLocalEndpoint(HttpClient client)
    {
        var address = client.BaseAddress;
        if (address is null || address.Scheme != Uri.UriSchemeHttp
            || address.Host != "127.0.0.1" || address.Port != 41955
            || address.AbsolutePath != "/" || address.Query.Length != 0)
        {
            throw new InvalidOperationException("LTX_DESKTOP_LOOPBACK_ONLY");
        }
        if (client.DefaultRequestHeaders.Authorization?.Scheme != "Bearer")
        {
            throw new InvalidOperationException("LTX_DESKTOP_PAIRED_BEARER_REQUIRED");
        }
    }

    public ValueTask DisposeAsync()
    {
        if (_ownsClient)
        {
            _http.Dispose();
        }
        return ValueTask.CompletedTask;
    }
}
