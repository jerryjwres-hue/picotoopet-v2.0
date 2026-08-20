using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v2 身体比例与遮挡：后腿藏在 torso 后，前腿盖住可见肩部插口，胸毛再压住内侧根部。</summary>
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

        AssertNear(112.0, torso.Width, "neutral torso 宽度没有按 plush 比例校准");
        AssertNear(90.0, torso.Height, "neutral torso 高度没有按 plush 比例校准");
        AssertNear(-56.0, Canvas.GetLeft(torso), "neutral torso X 锚点错误");
        AssertNear(-45.0, Canvas.GetTop(torso), "neutral torso Y 锚点错误");
        AssertNear(116.0, crouch.Width, "crouch torso 宽度没有同步 plush coverage");
        AssertNear(84.0, crouch.Height, "crouch torso 高度没有同步 plush coverage");
        AssertNear(108.0, stretch.Width, "stretch torso 宽度没有同步 plush coverage");
        AssertNear(96.0, stretch.Height, "stretch torso 高度没有同步 plush coverage");

        // 组合截图表明旧显示框把独立毛发部件横向压窄了 20%–40%，关节处像被切断。
        // 新 footprint 接近 manifest 逻辑尺寸，但 Pivot 仍必须沿用 manifest 的毛发 overlap 锚点。
        AssertImageBox(frontUpper, 31.0, 45.0, 17.0 / 34.0, 12.0 / 46.0, "front upper");
        AssertImageBox(frontLower, 30.0, 42.0, 16.0 / 32.0, 12.0 / 44.0, "front lower");
        AssertImageBox(frontPaw,   34.0, 24.0, 19.0 / 38.0, 12.0 / 28.0, "front paw");
        AssertImageBox(hindUpper,  33.0, 43.0, 19.0 / 38.0, 12.0 / 44.0, "hind upper");
        AssertImageBox(hindLower,  32.0, 41.0, 18.0 / 36.0, 12.0 / 42.0, "hind lower");
        AssertImageBox(hindPaw,    36.0, 26.0, 21.0 / 42.0, 13.0 / 30.0, "hind paw");

        Assert(Panel.GetZIndex(hindUpper) < Panel.GetZIndex(torso),
            "hind upper 必须藏在 torso 后，避免髋部接缝外露");
        Assert(Panel.GetZIndex(hindLower) > Panel.GetZIndex(hindUpper),
            "hind lower 必须覆盖 upper 的膝部 overlap，不能依赖 XAML 子项顺序");
        Assert(Panel.GetZIndex(hindPaw) > Panel.GetZIndex(hindLower),
            "hind paw 必须覆盖 lower 的踝部 overlap，避免睡眠/站立时出现断脚");

        // Shoulder socket cover : neutral torso 素材本身带浅色圆形插口，front upper 必须压在 torso 上方把它遮掉。
        // Chest overpaint       : chest 再位于 front upper 上方，只覆盖内侧根部，避免手臂像贴纸穿过胸毛。
        Assert(Panel.GetZIndex(frontUpper) > Panel.GetZIndex(torso),
            "front upper 必须盖住 torso 的浅色肩部插口，禁止再次出现机器人式圆环关节");
        Assert(Panel.GetZIndex(frontUpper) < Panel.GetZIndex(chest),
            "front upper 根部必须允许 chest 毛发二次遮挡，保持连续毛发轮廓");
        Assert(Panel.GetZIndex(frontLower) > Panel.GetZIndex(frontUpper),
            "front lower 必须覆盖 upper 的肘部 overlap，避免上下臂出现水平断口");
        Assert(Panel.GetZIndex(frontPaw) > Panel.GetZIndex(chest),
            "front paw 必须在 torso/chest 前方，保证落脚可读");
        Assert(Panel.GetZIndex(chest) > Panel.GetZIndex(torso),
            "胸毛兼容层必须继续位于 torso 上方");
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
        AssertNear(pivotX, element.RenderTransformOrigin.X, $"{label} X pivot 必须来自 manifest");
        AssertNear(pivotY, element.RenderTransformOrigin.Y, $"{label} Y pivot 必须来自 manifest");
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
