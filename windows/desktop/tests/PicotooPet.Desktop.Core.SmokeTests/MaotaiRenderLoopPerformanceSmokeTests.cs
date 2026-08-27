namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 高频渲染路径：无磁盘 IO、无 LINQ/集合分配，并且隐藏或卸载后严格退订。</summary>
internal static class MaotaiRenderLoopPerformanceSmokeTests
{
    public static void Run()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "AssistantPetPanel.Maotai.cs");
        var source = File.ReadAllText(path);

        Assert(source.Contains(
                "CompositionTarget.Rendering += MaotaiCompositionTarget_Rendering;",
                StringComparison.Ordinal),
            "茅台 v2 必须由 CompositionTarget.Rendering 驱动");
        Assert(source.Contains(
                "CompositionTarget.Rendering -= MaotaiCompositionTarget_Rendering;",
                StringComparison.Ordinal),
            "茅台 v2 隐藏/卸载后必须退订 Rendering");

        const string handlerStart = "private void MaotaiCompositionTarget_Rendering";
        const string handlerEnd   = "private void EnsureMaotaiV2Initialized";
        var start = source.IndexOf(handlerStart, StringComparison.Ordinal);
        var end   = source.IndexOf(handlerEnd, start, StringComparison.Ordinal);
        Assert(start >= 0 && end > start, "无法定位茅台 v2 Rendering 高频路径");

        var renderLoop = source[start..end];
        Assert(renderLoop.Contains("Math.Clamp(", StringComparison.Ordinal) &&
               renderLoop.Contains("now - _maotaiLastSeconds", StringComparison.Ordinal) &&
               renderLoop.Contains("MaotaiMaximumDeltaSeconds", StringComparison.Ordinal),
            "渲染入口必须继续保留 deltaTime clamp");

        string[] forbiddenTokens =
        [
            "File.",
            "Directory.",
            "LoadV2Part(",
            ".Select(",
            ".Where(",
            ".ToList(",
            ".ToArray(",
            "new List<",
            "new Dictionary<",
            "string.Format(",
        ];

        foreach (var token in forbiddenTokens)
        {
            Assert(!renderLoop.Contains(token, StringComparison.Ordinal),
                $"Rendering 高频路径禁止出现 {token}");
        }
    }

    private static string FindRepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory);
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        for (var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        throw new DirectoryNotFoundException("无法定位 PicotooPet 仓库根目录。");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
