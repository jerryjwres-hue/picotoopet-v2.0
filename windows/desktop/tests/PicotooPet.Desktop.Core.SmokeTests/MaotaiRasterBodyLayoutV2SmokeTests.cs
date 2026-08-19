using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v2 身体比例与遮挡：腿根藏在 torso 后，前爪在前，head 永远盖住身体。</summary>
internal static class MaotaiRasterBodyLayoutV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run() => WpfStaSmokeRunner.Run(RunCore);

    private static void RunCore()
    {
        var type = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterBodyLayout")
            ?? throw new InvalidOperationException("缺少 MaotaiRasterBodyLayout 身体光栅校准");
        var configure = type.GetMethod(
            "Configure",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiRasterBodyLayout 缺少 Configure");

        var body = new Canvas();
        var frontUpper = NamedImage("MaotaiV2FrontLeftUpper");
        var frontLower = NamedImage("MaotaiV2FrontLeftLower");
        var frontPaw   = NamedImage("MaotaiV2FrontLeftPaw");
        var hindUpper  = NamedImage("MaotaiV2HindLeftUpper");
        var hindLower  = NamedImage("MaotaiV2HindLeftLower");
        var hindPaw    = NamedImage("MaotaiV2HindLeftPaw");
        var torso      = NamedImage("MaotaiV2TorsoNeutral");
        var crouch     = NamedImage("MaotaiV2TorsoCrouch");
        var stretch    = NamedImage("MaotaiV2TorsoStretch");
        var chest      = NamedImage("MaotaiV2ChestFur");
        var head       = new Canvas { Name = "MaotaiV2HeadBone" };

        body.Children.Add(frontUpper);
        body.Children.Add(frontLower);
        body.Children.Add(frontPaw);
        body.Children.Add(hindUpper);
        body.Children.Add(hindLower);
        body.Children.Add(hindPaw);
        body.Children.Add(torso);
        body.Children.Add(crouch);
        body.Children.Add(stretch);
        body.Children.Add(chest);
        body.Children.Add(head);

        configure.Invoke(null, [body]);

        AssertNear(104.0, torso.Width, "neutral torso 宽度没有按最终比例校准");
        AssertNear(82.0, torso.Height, "neutral torso 高度没有按最终比例校准");
        AssertNear(-52.0, Canvas.GetLeft(torso), "neutral torso X 锚点错误");
        AssertNear(-41.0, Canvas.GetTop(torso), "neutral torso Y 锚点错误");

        // Visual-fit contract: image boxes may grow around the same pivots, but IK joint coordinates never change.
        AssertImageBox(frontUpper, 26.0, 43.0, 0.50, 0.15, "front upper");
        AssertImageBox(frontLower, 25.0, 40.0, 0.50, 0.15, "front lower");
        AssertImageBox(frontPaw,   27.0, 20.0, 0.50, 0.50, "front paw");
        AssertImageBox(hindUpper,  26.0, 42.0, 0.50, 0.15, "hind upper");
        AssertImageBox(hindLower,  25.0, 39.0, 0.50, 0.15, "hind lower");
        AssertImageBox(hindPaw,    26.0, 20.0, 0.50, 0.50, "hind paw");

        Assert(Panel.GetZIndex(hindUpper) < Panel.GetZIndex(torso),
            "hind upper 必须藏在 torso 后，避免髋部接缝外露");
        Assert(Panel.GetZIndex(frontUpper) < Panel.GetZIndex(torso),
            "front upper 必须藏在 torso 后，不能像机械手臂贴在胸口");
        Assert(Panel.GetZIndex(frontLower) < Panel.GetZIndex(torso),
            "front lower 的上端必须允许被 torso 遮住");
        Assert(Panel.GetZIndex(frontPaw) > Panel.GetZIndex(torso),
            "front paw 必须在 torso 前方，保证落脚可读");
        Assert(Panel.GetZIndex(chest) > Panel.GetZIndex(torso),
            "胸毛必须覆盖 torso 接缝而不是被压在后面");
        Assert(Panel.GetZIndex(head) > Panel.GetZIndex(frontPaw),
            "head 必须位于身体与爪子上方，避免身体层穿脸");
    }

    private static Image NamedImage(string name) => new() { Name = name };

    private static void AssertImageBox(
        FrameworkElement element,
        double width,
        double height,
        double pivotX,
        double pivotY,
        string label)
    {
        AssertNear(width, element.Width, $"{label} 显示宽度错误");
        AssertNear(height, element.Height, $"{label} 显示高度错误");
        AssertNear(-(width * pivotX), Canvas.GetLeft(element), $"{label} X pivot 被显示校准移动");
        AssertNear(-(height * pivotY), Canvas.GetTop(element), $"{label} Y pivot 被显示校准移动");
    }

    private static void AssertNear(double expected, double actual, string message)
    {
        if (!double.IsFinite(actual) || Math.Abs(expected - actual) > 0.000001)
        {
            throw new InvalidOperationException($"{message}；expected={expected:F3}, actual={actual:F3}");
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
