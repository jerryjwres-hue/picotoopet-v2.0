using System.IO;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Versioning;

/// <summary>从发布输出中的唯一版本资源生成所有用户可见版本文案。</summary>
public static class ProductVersionInfo
{
    /// <summary>发布输出中唯一版本资源的固定文件名。</summary>
    public const string FileName = "product-version.txt";

    private static readonly Regex ProductVersionPattern = new(
        "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    /// <summary>当前四段式用户产品版本；文件缺失或格式错误时启动失败关闭。</summary>
    public static string Current { get; } = Parse(
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, FileName)));

    /// <summary>Windows 主窗口标题。</summary>
    public static string WindowTitle => $"Picotoo Pet AI {Current}";

    /// <summary>Control Center 左上角副标题。</summary>
    public static string ControlCenterSubtitle => $"Control Center · v{Current}";

    /// <summary>规范化并验证四段式数字版本。</summary>
    public static string Parse(string raw)
    {
        ArgumentNullException.ThrowIfNull(raw);
        var value = raw.Trim();
        if (!ProductVersionPattern.IsMatch(value))
        {
            throw new InvalidDataException($"产品版本必须是四段数字：{raw}");
        }
        return value;
    }
}
