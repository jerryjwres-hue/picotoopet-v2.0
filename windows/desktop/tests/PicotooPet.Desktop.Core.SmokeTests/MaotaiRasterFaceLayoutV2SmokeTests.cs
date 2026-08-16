using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 面部光栅层级：口鼻底必须在眼睛下方，动态五官必须对齐当前 head shell。</summary>
internal static class MaotaiRasterFaceLayoutV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var type = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterFaceLayout")
            ?? throw new InvalidOperationException("缺少 MaotaiRasterFaceLayout 面部光栅校准");
        var configure = type.GetMethod(
            "Configure",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiRasterFaceLayout 缺少 Configure");
        var pupilX = type.GetMethod(
            "CalibratePupilX",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiRasterFaceLayout 缺少 CalibratePupilX");
        var pupilY = type.GetMethod(
            "CalibratePupilY",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiRasterFaceLayout 缺少 CalibratePupilY");

        var head = new Canvas();
        var muzzle = NamedImage("MaotaiV2Muzzle");
        var eye = NamedImage("MaotaiV2EyeLeftOpen");
        var pupil = NamedImage("MaotaiV2PupilLeft");
        var brow = NamedImage("MaotaiV2BrowLeft");
        var mouth = NamedImage("MaotaiV2MouthSmile");
        head.Children.Add(muzzle);
        head.Children.Add(eye);
        head.Children.Add(pupil);
        head.Children.Add(brow);
        head.Children.Add(mouth);

        configure.Invoke(null, [head]);

        AssertNear(-13.0, Canvas.GetTop(muzzle), "muzzle 垂直校准错误");
        AssertNear(-16.0, Canvas.GetTop(eye), "眼睛垂直校准错误");
        AssertNear(-2.0, Canvas.GetTop(mouth), "嘴型垂直校准错误");
        Assert(Panel.GetZIndex(muzzle) < Panel.GetZIndex(eye),
            "muzzle 必须在眼睛下方，否则会把独立眼睛盖掉");
        Assert(Panel.GetZIndex(eye) < Panel.GetZIndex(pupil),
            "瞳孔必须在眼睛上方，否则自主视线不可见");
        Assert(Panel.GetZIndex(pupil) < Panel.GetZIndex(brow),
            "眉毛必须保持在眼睛/瞳孔上方");
        Assert(Panel.GetZIndex(brow) < Panel.GetZIndex(mouth),
            "动态嘴型必须是面部最上层之一，避免底图旧嘴穿帮");

        AssertNear(-11.0, InvokeDouble(pupilX, -6.0, true), "左瞳孔基础位置没有对齐左眼中心");
        AssertNear(11.0, InvokeDouble(pupilX, 6.0, false), "右瞳孔基础位置没有对齐右眼中心");
        AssertNear(-7.0, InvokeDouble(pupilY, -2.0), "瞳孔垂直位置没有对齐眼球中心");
    }

    private static Image NamedImage(string name) => new() { Name = name };

    private static double InvokeDouble(MethodInfo method, params object[] args)
    {
        var result = method.Invoke(null, args);
        return result is double value
            ? value
            : throw new InvalidOperationException($"{method.Name} 必须返回 double");
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
