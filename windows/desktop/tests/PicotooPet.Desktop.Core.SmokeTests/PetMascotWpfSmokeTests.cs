using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证茅台互动宠物控件保持原生 WPF、可布局，并只暴露轻量宿主接口。</summary>
internal static class PetMascotWpfSmokeTests
{
    private const string ControlTypeName =
        "PicotooPet.Desktop.Controls.PetMascot.PetMascotControl";

    /// <summary>不干扰历史绑定 RED 见证；正常 smoke 退出前执行新增合同。</summary>
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Contains(
                "--expect-task-center-legacy-binding-failure",
                StringComparer.Ordinal))
        {
            return;
        }

        AppDomain.CurrentDomain.ProcessExit += static (_, _) =>
        {
            try
            {
                Run();
                Console.WriteLine("MAOTAI_PET_WPF_SMOKE=PASS");
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine($"MAOTAI_PET_WPF_SMOKE=FAIL | {exception}");
                Environment.ExitCode = 1;
            }
        };
    }

    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunContract();
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

    private static void RunContract()
    {
        var desktopAssembly = typeof(OperatorHomePage).Assembly;
        var controlType = desktopAssembly.GetType(ControlTypeName, throwOnError: false);

        if (controlType is null)
        {
            throw new InvalidOperationException("茅台互动宠物控件尚未实现");
        }

        SmokeAssert.True(
            typeof(FrameworkElement).IsAssignableFrom(controlType),
            "茅台互动宠物控件必须保持原生 WPF FrameworkElement");

        var stateProperty = controlType.GetProperty("State");
        SmokeAssert.True(stateProperty is not null, "茅台控件缺少 State 状态入口");

        var newTaskEvent = controlType.GetEvent("NewTaskRequested");
        var progressEvent = controlType.GetEvent("ProgressRequested");
        SmokeAssert.True(newTaskEvent is not null, "茅台控件缺少 NewTaskRequested 轻量事件");
        SmokeAssert.True(progressEvent is not null, "茅台控件缺少 ProgressRequested 轻量事件");

        var calloutMethod = controlType.GetMethod("ShowInteractionCallout");
        SmokeAssert.True(calloutMethod is not null, "茅台控件缺少点击气泡入口");

        var instance = Activator.CreateInstance(controlType) as FrameworkElement;
        if (instance is null)
        {
            throw new InvalidOperationException("茅台互动宠物控件无法安全实例化");
        }

        instance.Measure(new Size(360, 360));
        instance.Arrange(new Rect(0, 0, 360, 360));
        instance.UpdateLayout();
        instance.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(instance.IsMeasureValid, "茅台控件 Measure 未完成");
        SmokeAssert.True(instance.IsArrangeValid, "茅台控件 Arrange 未完成");
        SmokeAssert.True(instance.ActualWidth > 0, "茅台控件实际宽度无效");
        SmokeAssert.True(instance.ActualHeight > 0, "茅台控件实际高度无效");
        SmokeAssert.True(
            instance.MinWidth >= 300 && instance.MinWidth <= 320,
            "茅台陪伴型组件宽度必须保持在 300–320px");

        var mascotImage = instance.FindName("MascotImage") as System.Windows.Controls.Image;
        SmokeAssert.True(mascotImage is not null, "茅台控件缺少真实位图显示区域");
        SmokeAssert.True(mascotImage?.Source is not null, "茅台 PNG 位图资源没有成功加载");
        SmokeAssert.True(
            mascotImage?.Width >= 260 && mascotImage?.Width <= 280,
            "茅台主体视觉尺寸必须保持在 260–280px");

        var calloutBorder = instance.FindName("CalloutBorder") as System.Windows.Controls.Border;
        SmokeAssert.True(calloutBorder is not null, "茅台控件缺少陪伴型气泡容器");
        SmokeAssert.True(
            calloutBorder?.MaxWidth >= 286 && calloutBorder?.MaxWidth <= 304,
            "茅台气泡宽度必须与陪伴型右栏比例匹配");

        var homePage = new OperatorHomePage();
        var hostedMascot = homePage.FindName("MaotaiMascot") as FrameworkElement;
        SmokeAssert.True(hostedMascot is not null, "首页尚未接入 MaotaiMascot 轻量组件");
    }
}
