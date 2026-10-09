using System.Security.Cryptography;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>闭集字体候选；FileName 位于 Windows Fonts 目录，Family 仅用于报告。</summary>
public sealed record WindowsOverlayFontCandidate(string FileName, string Family);

/// <summary>已解析的系统字体：名称、身份 SHA-256 与字节（仅用于复制到隔离工作目录）。</summary>
public sealed record ResolvedOverlayFont(string FileName, string Family, string IdentitySha256, byte[] Bytes);

/// <summary>
/// font.windows-system-sans.v1：闭集候选、只在系统 Fonts 目录解析、拒绝重解析点、限制大小、
/// 并以 cmap 校验字形覆盖。不存在调用方字体/路径输入，也不下载字体。
/// </summary>
public sealed class WindowsTextOverlayFontPolicy
{
    public const long MaxFontBytes = 64L * 1024 * 1024;

    public static readonly IReadOnlyList<WindowsOverlayFontCandidate> EnglishCandidates =
    [
        new("arial.ttf", "Arial"),
        new("segoeui.ttf", "Segoe UI"),
        new("msyh.ttc", "Microsoft YaHei"),
    ];

    public static readonly IReadOnlyList<WindowsOverlayFontCandidate> ChineseCandidates =
    [
        new("msyh.ttc", "Microsoft YaHei"),
        new("Deng.ttf", "DengXian"),
        new("simhei.ttf", "SimHei"),
        new("simsun.ttc", "SimSun"),
    ];

    private readonly string _fontsDirectory;

    /// <summary>生产构造：只使用 Windows 系统 Fonts 文件夹。</summary>
    public WindowsTextOverlayFontPolicy()
        : this(Environment.GetFolderPath(Environment.SpecialFolder.Fonts))
    {
    }

    /// <summary>组合根/测试接缝：Fonts 目录由代码固定，永远不来自用户或 Core 输入。</summary>
    public WindowsTextOverlayFontPolicy(string fontsDirectory)
    {
        _fontsDirectory = fontsDirectory;
    }

    /// <summary>含任何汉字表意字符 → 中文策略；否则英文策略。</summary>
    public static IReadOnlyList<WindowsOverlayFontCandidate> CandidatesFor(string text) =>
        ContainsHan(text) ? ChineseCandidates : EnglishCandidates;

    public static bool ContainsHan(string text)
    {
        foreach (var rune in text.EnumerateRunes())
        {
            var value = rune.Value;
            if (value is >= 0x3400 and <= 0x4DBF
                or >= 0x4E00 and <= 0x9FFF
                or >= 0xF900 and <= 0xFAFF
                or >= 0x20000 and <= 0x2FA1F)
            {
                return true;
            }
        }
        return false;
    }

    /// <summary>按固定顺序取第一个存在且覆盖全部字形的候选；否则返回有界错误码。</summary>
    public ResolvedOverlayFont Resolve(string text)
    {
        var sawFont = false;
        foreach (var candidate in CandidatesFor(text))
        {
            var path = Path.Combine(_fontsDirectory, candidate.FileName);
            if (!File.Exists(path))
            {
                continue;
            }
            var attributes = File.GetAttributes(path);
            if ((attributes & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0)
            {
                continue;
            }
            var length = new FileInfo(path).Length;
            if (length is <= 0 or > MaxFontBytes)
            {
                continue;
            }
            sawFont = true;
            var bytes = File.ReadAllBytes(path);
            if (WindowsSfntCmap.TryCovers(bytes, text, out var covers) && covers)
            {
                return new ResolvedOverlayFont(
                    candidate.FileName,
                    candidate.Family,
                    Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
                    bytes);
            }
        }
        throw new TextOverlayException(
            sawFont ? TextOverlayException.GlyphMissing : TextOverlayException.FontUnavailable);
    }
}
