using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>复现重连快照替换导航集合时 WPF 选择项短暂回写 null 的闪退。</summary>
internal static class ShellNavigationReconnectWpfSmokeTests
{
    /// <summary>真实 TwoWay ListBox 绑定在重连期间不得终止 UI 线程。</summary>
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var shell = ShellViewModel.CreateForSmokeTest(
                    ControlCenterCapabilities.Legacy22 with
                    {
                        ResultList = true,
                        ResultPreview = true,
                    });
                shell.Navigate(NavigationRoute.Results);

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

                // WPF 在 ItemsSource 被替换时会短暂清空 SelectedItem，再恢复对应项。
                list.SelectedItem = null;
                list.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);

                SmokeAssert.True(
                    shell.CurrentRoute == NavigationRoute.Results,
                    "重连期间的瞬时空选择不得改变当前页面");
                SmokeAssert.True(
                    shell.SelectedNavigationItem.Route == NavigationRoute.Results,
                    "重连期间的瞬时空选择不得清除已选导航");
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
