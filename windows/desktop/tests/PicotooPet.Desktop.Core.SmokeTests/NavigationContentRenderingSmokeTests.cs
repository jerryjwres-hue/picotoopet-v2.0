using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Shell 内容宿主会把页面 ViewModel 通过生产 DataTemplate 渲染成真实页面。</summary>
internal static class NavigationContentRenderingSmokeTests
{
    /// <summary>在专用 STA 线程加载生产资源并传播任意渲染失败。</summary>
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

    /// <summary>加载生产 App.xaml 资源并执行即时与延迟内容的真实 WPF 布局。</summary>
    private static void RunOnStaThread()
    {
        var application = Application.Current as App ?? new App();
        application.InitializeComponent();

        VerifyDelayedContentRendering();
        VerifyImmediateContentRendering();
    }

    /// <summary>模拟 Shell 首次布局时内容绑定尚未到达，随后再发布当前页面。</summary>
    private static void VerifyDelayedContentRendering()
    {
        var host = new NavigationContentHost();
        var root = CreateRoot(host);

        Layout(root);
        SmokeAssert.True(
            VisualTreeHelper.GetChildrenCount(host) > 0,
            "空 NavigationContentHost 首次布局未创建基础 ContentPresenter");

        host.Content = CreateTaskCenter();
        Layout(root);

        AssertTaskCenterVisible(host, "延迟内容");
    }

    /// <summary>保留内容在首次布局前已到达的原有渲染路径。</summary>
    private static void VerifyImmediateContentRendering()
    {
        var host = new NavigationContentHost
        {
            Content = CreateTaskCenter(),
        };
        var root = CreateRoot(host);

        Layout(root);

        AssertTaskCenterVisible(host, "即时内容");
    }

    private static TaskCenterPageViewModel CreateTaskCenter() =>
        TaskCenterPageViewModel.CreateForSmokeTest(
            Array.Empty<TaskRecord>(),
            WorkerSnapshot.NotDeployed);

    private static System.Windows.Controls.Border CreateRoot(
        NavigationContentHost host) => new()
    {
        Width  = 960,
        Height = 680,
        Child  = host,
    };

    private static void Layout(FrameworkElement root)
    {
        root.Measure(new Size(960, 680));
        root.Arrange(new Rect(0, 0, 960, 680));
        root.UpdateLayout();
        root.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        root.UpdateLayout();
    }

    private static void AssertTaskCenterVisible(
        NavigationContentHost host,
        string scenario)
    {
        var page = FindVisualDescendant<TaskCenterPage>(host);
        if (page is null)
        {
            throw new InvalidOperationException(
                $"{scenario}未通过生产 DataTemplate 渲染 TaskCenterPage");
        }

        SmokeAssert.True(
            page.ActualWidth > 0 && page.ActualHeight > 0,
            $"{scenario}已创建 TaskCenterPage，但没有可见布局尺寸");
    }

    private static T? FindVisualDescendant<T>(DependencyObject parent)
        where T : DependencyObject
    {
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is T match)
            {
                return match;
            }

            var nested = FindVisualDescendant<T>(child);
            if (nested is not null)
            {
                return nested;
            }
        }

        return null;
    }
}
