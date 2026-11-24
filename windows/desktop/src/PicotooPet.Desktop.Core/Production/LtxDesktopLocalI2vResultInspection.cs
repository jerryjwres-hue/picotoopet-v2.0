using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>一次已经发生的 I2V 提交身份；不包含凭据或可能泄露签名的媒体 URL。</summary>
public sealed record LtxDesktopGenerationExpectation(
    string GenerationId,
    string StartFrameAssetId,
    string Prompt,
    int Seed);

/// <summary>只读远端记录见证；此记录绝不能充当 Core ProductionTask CommitResult。</summary>
public sealed record LtxDesktopGenerationInspection(
    string GenerationId,
    string VideoAssetId,
    string MediaType,
    string Lane,
    int DurationSeconds,
    int Fps,
    int Seed,
    bool ResultIsLocal,
    bool SubmissionReceiptIndependentlyBoundToCore,
    bool StartFrameBytesIndependentlyVerified,
    bool MediaBytesDownloaded,
    bool MediaGeometryVerified,
    bool CanCommitProductionResult,
    int GpuPost);

public sealed partial class LtxDesktopLocalI2vPreflightClient
{
    /// <summary>
    /// 只 GET /api/generations/{id}；没有上传视频、下载签名文件或调用 GPU。
    /// 即使 vendor 报成功，本函数也不会批准生产或声明 MP4 字节已核验。
    /// </summary>
    public async Task<LtxDesktopGenerationInspection> InspectCompletedGenerationAsync(
        LtxDesktopGenerationExpectation expected,
        CancellationToken cancellationToken = default)
    {
        // 01. 只接受确定的 generation UUID / startFrame asset UUID；
        //     不从未核实的历史记录中自动选择「最近一个成功」。
        ArgumentNullException.ThrowIfNull(expected);
        if (!Guid.TryParseExact(expected.GenerationId, "D", out _)
            || !Guid.TryParseExact(expected.StartFrameAssetId, "D", out _)
            || string.IsNullOrWhiteSpace(expected.Prompt)
            || expected.Prompt.Length > 10_000
            || expected.Seed < 0)
        {
            throw new InvalidOperationException("LTX_GENERATION_EXPECTATION_INVALID");
        }

        var generation = await GetAsync(
            "api/generations/" + expected.GenerationId,
            cancellationToken).ConfigureAwait(false);

        // 02. 用本地 LTX Desktop 的持久化记录重新确认 ID、明确完成
        //     状态和 lane。历史 S1/S2 缺 lane，不能凭本地 HTTP 地址推断。
        if (ReadText(generation, "id") != expected.GenerationId)
        {
            throw new InvalidDataException("LTX_GENERATION_ID_CONFLICT");
        }
        if (ReadText(generation, "status") != "succeeded")
        {
            throw new InvalidOperationException("LTX_GENERATION_NOT_SUCCEEDED");
        }
        if (ReadText(generation, "lane") != "local")
        {
            throw new InvalidOperationException("LTX_GENERATION_LOCAL_LANE_UNVERIFIED");
        }

        // 03. 对照原始客户端实际读取的 spec.params 和 I2V payload。
        //     如果 vendor 版本没有提供这些字段，保持 UNVERIFIED。
        var spec = generation["spec"] as JsonObject
            ?? throw new InvalidDataException("LTX_GENERATION_SPEC_UNVERIFIED");
        var p = spec["params"] as JsonObject
            ?? throw new InvalidDataException("LTX_GENERATION_SPEC_UNVERIFIED");
        var inputs = spec["inputs"] as JsonObject
            ?? throw new InvalidDataException("LTX_GENERATION_INPUT_UNVERIFIED");
        var start = inputs["startFrame"] as JsonObject
            ?? throw new InvalidDataException("LTX_GENERATION_INPUT_UNVERIFIED");
        if (ReadText(start, "assetId") != expected.StartFrameAssetId)
        {
            throw new InvalidDataException("LTX_GENERATION_START_FRAME_ASSET_CONFLICT");
        }
        if (ReadText(p, "prompt") != expected.Prompt
            || ReadText(p, "model") != "ltx-2.5-fast"
            || ReadText(p, "resolution") != "720p"
            || ReadText(p, "aspectRatio") != "9:16"
            || ReadInt(p, "duration") != 4
            || ReadInt(p, "fps") != 24
            || ReadInt(p, "seed") != expected.Seed
            || ReadText(p, "cameraMotion") != "none"
            || ReadText(p, "negativePrompt") != ""
            || ReadText(p, "promptProvenance") != "typed")
        {
            throw new InvalidDataException("LTX_GENERATION_FROZEN_PARAMETERS_CONFLICT");
        }

        // 04. 只接受一个确定的本地视频资产。可能带令牌的签名
        //     bytes_url 只做白名单验证，绝不返回、打印或保存该 URL。
        var outputs = generation["outputs"] as JsonArray
            ?? throw new InvalidDataException("LTX_GENERATION_OUTPUTS_UNVERIFIED");
        var videos = outputs.OfType<JsonObject>()
            .Where(item => ReadText(item, "media_kind") == "video")
            .ToArray();
        if (videos.Length != 1 || outputs.Any(item => item is not JsonObject))
        {
            throw new InvalidDataException("LTX_GENERATION_VIDEO_OUTPUT_AMBIGUOUS");
        }
        var video = videos[0];
        var id = ReadText(video, "id");
        var mime = ReadText(video, "mime_type");
        var signedUrl = ReadText(video, "bytes_url");
        if (!Guid.TryParseExact(id, "D", out _)
            || mime is not ("video/mp4" or "video/webm")
            || signedUrl is null
            || !IsVendorSignedAssetPath(signedUrl, id!))
        {
            throw new InvalidDataException("LTX_GENERATION_SIGNED_VIDEO_REF_INVALID");
        }

        // 05. 明确隔离 vendor 成功与正式 Core Commit。尚未核对源图
        //     上传字节、视频实际大小/画幅、签名 Attempt 或 Owner 许可。
        return new LtxDesktopGenerationInspection(
            expected.GenerationId, id!, mime!, "local", 4, 24, expected.Seed,
            ResultIsLocal: true,
            SubmissionReceiptIndependentlyBoundToCore: false,
            StartFrameBytesIndependentlyVerified: false,
            MediaBytesDownloaded: false,
            MediaGeometryVerified: false,
            CanCommitProductionResult: false,
            GpuPost: 0);
    }

    private static string? ReadText(JsonObject node, string property)
    {
        return node[property] is JsonValue v && v.TryGetValue<string>(out var s)
            ? s : null;
    }

    private static int? ReadInt(JsonObject node, string property)
    {
        return node[property] is JsonValue v && v.TryGetValue<int>(out var number)
            ? number : null;
    }

    private static bool IsVendorSignedAssetPath(string url, string expectedAssetId)
    {
        // 06. The vendor's private bytes URL is relative, never a full
        //     internet URL, path traversal, fragments, CRLF or host redirects.
        if (url.Length is < 60 or > 4096 || url.Any(char.IsControl))
        {
            return false;
        }
        var match = Regex.Match(url,
            @"\A/api/assets/([0-9a-fA-F-]{36})/bytes\?([^#/?\r\n]+)\z",
            RegexOptions.CultureInvariant);
        return match.Success
            && string.Equals(match.Groups[1].Value, expectedAssetId, StringComparison.Ordinal)
            && match.Groups[2].Value.Length > 0
            && Uri.TryCreate(FixedBaseAddress, url, out var absolute)
            && absolute.Host == "127.0.0.1"
            && absolute.Port == 41955
            && absolute.Fragment.Length == 0;
    }
}
