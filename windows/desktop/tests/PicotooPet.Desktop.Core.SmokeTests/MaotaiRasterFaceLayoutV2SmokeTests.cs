using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 面部光栅层级：耳根、口鼻、动态五官都必须对齐当前 head shell。</summary>
internal static class MaotaiRasterFaceLayoutV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run() => WpfStaSmokeRunner.Run(RunCore);

    private static void RunCore()
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
        var ear = NamedImage("MaotaiV2EarLeft");
        var band = NamedImage("MaotaiV2HeadphoneBand");
        var headShell = NamedImage("MaotaiV2Head");
        var muzzle = NamedImage("MaotaiV2Muzzle");
        var eye = NamedImage("MaotaiV2EyeLeftOpen");
        var pupil = NamedImage("MaotaiV2PupilLeft");
        var brow = NamedImage("MaotaiV2BrowLeft");
        var mouth = NamedImage("MaotaiV2MouthSmile");
        var cup = NamedImage("MaotaiV2HeadphoneLeft");
        head.Children.Add(ear);
        head.Children.Add(band);
        head.Children.Add(headShell);
        head.Children.Add(muzzle);
        head.Children.Add(eye);
        head.Children.Add(pupil);
        head.Children.Add(brow);
        head.Children.Add(mouth);
        head.Children.Add(cup);

        configure.Invoke(null, [head]);

        var visualScale = head.LayoutTransform as ScaleTransform
            ?? throw new InvalidOperationException("head 必须有独立的静态视觉缩放，不能改 Motion Engine 的动态 HeadScale");
        AssertNear(0.90, visualScale.ScaleX, "head 静态视觉宽度比例错误");
        AssertNear(0.90, visualScale.ScaleY, "head 静态视觉高度比例错误");

        AssertNear(-20.5, Canvas.GetTop(ear), "耳根没有压入 head 毛发轮廓");
        AssertNear(-13.0, Canvas.GetTop(muzzle), "muzzle 垂直校准错误");
        AssertNear(-16.0, Canvas.GetTop(eye), "眼睛垂直校准错误");
        AssertNear(-2.0, Canvas.GetTop(mouth), "嘴型垂直校准错误");
        Assert(Panel.GetZIndex(ear) < Panel.GetZIndex(band), "耳朵应位于头戴式耳机带后方");
        Assert(Panel.GetZIndex(band) < Panel.GetZIndex(headShell), "head 必须盖住耳根与耳机带下缘");
        Assert(Panel.GetZIndex(headShell) < Panel.GetZIndex(muzzle), "muzzle 必须位于 head shell 上方");
        Assert(Panel.GetZIndex(muzzle) < Panel.GetZIndex(eye),
            "muzzle 必须在眼睛下方，否则会把独立眼睛盖掉");
        Assert(Panel.GetZIndex(eye) < Panel.GetZIndex(pupil),
            "瞳孔必须在眼睛上方，否则自主视线不可见");
        Assert(Panel.GetZIndex(pupil) < Panel.GetZIndex(brow),
            "眉毛必须保持在眼睛/瞳孔上方");
        Assert(Panel.GetZIndex(brow) < Panel.GetZIndex(mouth),
            "动态嘴型必须是面部最上层之一，避免底图旧嘴穿帮");
        Assert(Panel.GetZIndex(mouth) < Panel.GetZIndex(cup),
            "耳机耳罩必须位于面部最外层，避免穿进脸颊");

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

/// <summary>WPF smoke 的最小 STA 边界；避免 async 测试入口把 UI 构造落到 MTA。</summary>
internal static class WpfStaSmokeRunner
{
    public static void Run(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (Thread.CurrentThread.GetApartmentState() == ApartmentState.STA)
        {
            action();
            return;
        }

        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }
}
