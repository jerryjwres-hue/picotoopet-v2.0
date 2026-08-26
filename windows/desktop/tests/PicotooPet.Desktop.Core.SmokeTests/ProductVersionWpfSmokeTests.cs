using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Versioning;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 绑定和布局管线中冻结 Superpower 公共身份并独立校验工程版本。</summary>
internal static class ProductVersionWpfSmokeTests
{
    /// <summary>验证唯一工程版本资源、OneWay 绑定和布局后的公共产品文案。</summary>
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunOnStaThread();
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

    private static void RunOnStaThread()
    {
        SmokeAssert.True(
            ProductVersionInfo.Current == "2.3.27.1",
            "Windows 内部工程版本资源错误");

        using var viewModel = ShellViewModel.CreateForSmokeTest(
            ControlCenterCapabilities.Legacy22);
        var subtitle = new TextBlock();
        var window = new Window
        {
            DataContext = viewModel,
            Content = subtitle,
        };

        BindingOperations.SetBinding(
            window,
            Window.TitleProperty,
            new Binding(nameof(ShellViewModel.WindowTitle))
            {
                Mode = BindingMode.OneWay,
            });
        BindingOperations.SetBinding(
            subtitle,
            TextBlock.TextProperty,
            new Binding(nameof(ShellViewModel.ControlCenterSubtitle))
            {
                Mode = BindingMode.OneWay,
            });

        window.Measure(new Size(900, 700));
        window.Arrange(new Rect(0, 0, 900, 700));
        window.UpdateLayout();
        window.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        window.UpdateLayout();

        // Public identity gate     正常 UI 只展示 Superpower v1.0；2.3.x 仅作为内部工程元数据保留。
        SmokeAssert.True(
            window.Title == "PicotooPet AI — Superpower v1.0",
            "窗口标题必须只显示 Superpower v1.0 公共产品身份");
        SmokeAssert.True(
            subtitle.Text == "Superpower v1.0 · Control Center",
            "控制中心副标题公共产品身份错误");

        window.Close();
    }
}
