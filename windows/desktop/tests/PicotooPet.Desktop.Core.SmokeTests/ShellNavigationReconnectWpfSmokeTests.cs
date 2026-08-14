using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>复现重连快照替换五项简单导航时 WPF 选择项短暂回写 null 的闪退。</summary>
internal static class ShellNavigationReconnectWpfSmokeTests
{
    /// <summary>真实 TwoWay ListBox 绑定在高级子页和重连期间不得终止 UI 线程。</summary>
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                using var shell = ShellViewModel.CreateForSmokeTest(
                    ControlCenterCapabilities.Legacy22 with
                    {
                        ResultList = true,
                        ResultPreview = true,
                    });
                shell.Navigate(NavigationRoute.Results);

                SmokeAssert.True(
                    shell.CurrentRoute == NavigationRoute.Results,
                    "高级 Results 路由没有打开");
                SmokeAssert.True(
                    shell.SelectedNavigationItem.Route == NavigationRoute.AdvancedHome,
                    "高级 Results 打开后侧栏必须保持高级选中");

                var list = new ListBox
                {
                    ItemsSource = shell.NavigationItems,
                };
                BindingOperations.SetBinding(
                    list,
                    ListBox.SelectedItemProperty,
                    new Binding(nameof(ShellViewModel.SelectedNavigationItem))
                    {
                        Source = shell,
                        Mode = BindingMode.TwoWay,
                        UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged,
                    });
                list.Measure(new Size(240, 700));
                list.Arrange(new Rect(0, 0, 240, 700));
                list.UpdateLayout();

                // WPF 在 ItemsSource 被替换时会短暂清空 SelectedItem；这不是用户导航。
                list.SelectedItem = null;
                list.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);

                SmokeAssert.True(
                    shell.CurrentRoute == NavigationRoute.Results,
                    "重连期间的瞬时空选择不得改变当前高级页面");
                SmokeAssert.True(
                    shell.SelectedNavigationItem.Route == NavigationRoute.AdvancedHome,
                    "重连期间的瞬时空选择不得清除高级侧栏状态");
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
            throw new InvalidOperationException("重连导航 WPF 回归失败。", failure);
        }
    }
}
