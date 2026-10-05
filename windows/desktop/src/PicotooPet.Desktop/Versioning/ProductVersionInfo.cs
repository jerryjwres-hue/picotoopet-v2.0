using System.IO;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Versioning;

/// <summary>从发布输出中的唯一版本资源保留工程版本，并生成稳定的 Superpower 公共产品身份。</summary>
public static class ProductVersionInfo
{
    /// <summary>发布输出中唯一工程版本资源的固定文件名。</summary>
    public const string FileName = "product-version.txt";

    /// <summary>统一的用户可见产品名；不改变既有 EXE/安装生命周期。</summary>
    public const string ProductName = "PicotooPet AI";

    /// <summary>当前自主能力层的公共产品标识。</summary>
    public const string SuperpowerLabel = "Superpower v1.0";

    private static readonly Regex ProductVersionPattern = new(
        "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    /// <summary>内部四段式工程版本；用于安装兼容、诊断、日志、清单与自检。</summary>
    public static string Current { get; } = Parse(
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, FileName)));

    /// <summary>Windows 主窗口只显示稳定公共产品身份，不暴露 2.3.x 工程流水版本。</summary>
    public static string WindowTitle => $"{ProductName} — {SuperpowerLabel}";

    /// <summary>Control Center 副标题只显示能力代际和角色；工程版本留在诊断面。</summary>
    public static string ControlCenterSubtitle => $"{SuperpowerLabel} · Control Center";

    /// <summary>规范化并验证内部四段式数字工程版本。</summary>
    public static string Parse(string raw)
    {
        ArgumentNullException.ThrowIfNull(raw);
        var value = raw.Trim();
        if (!ProductVersionPattern.IsMatch(value))
        {
            throw new InvalidDataException($"产品工程版本必须是四段数字：{raw}");
        }
        return value;
    }
}
