namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 的无撕裂与连续渲染合同。</summary>
internal static class MaotaiNaturalMotionV2SmokeTests
{
    /// <summary>验证 v2 可见路径不再裁完整图，并使用显示器渲染节拍推进姿态。</summary>
    public static void Run()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "AssistantPetPanel.xaml"));
        var code = File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "AssistantPetPanel.Maotai.cs"));

        Assert(
            !xaml.Contains("<Image.Clip>", StringComparison.Ordinal),
            "v2 可见茅台禁止从完整角色图 Clip 裁出头/爪/尾；该结构会产生撕裂和重影");
        Assert(
            code.Contains("CompositionTarget.Rendering", StringComparison.Ordinal),
            "v2 必须由 CompositionTarget.Rendering 连续推进姿态");
        Assert(
            !code.Contains("Interval = TimeSpan.FromMilliseconds(220)", StringComparison.Ordinal),
            "v2 禁止 220ms DispatcherTimer 作为运动主时钟");
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        var current = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (current is not null)
        {
            if (Directory.Exists(Path.Combine(current.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(current.FullName, "pyproject.toml")))
            {
                return current.FullName;
            }

            current = current.Parent;
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
