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

/// <summary>在真实 STA WPF 绑定和布局管线中冻结用户可见产品版本。</summary>
internal static class ProductVersionWpfSmokeTests
{
    /// <summary>验证唯一版本资源、OneWay 绑定和布局后的精确文案。</summary>
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
            ProductVersionInfo.Current == "2.3.7.1",
            "Windows 产品版本资源错误");

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

        SmokeAssert.True(
            window.Title == "Picotoo Pet AI 2.3.7.1",
            "窗口标题产品版本错误");
        SmokeAssert.True(
            subtitle.Text == "Control Center · v2.3.7.1",
            "左上角产品版本错误");

        window.Close();
    }
}
