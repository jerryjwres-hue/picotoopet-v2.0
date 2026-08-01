using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Control Center 一级导航与能力关闭策略。</summary>
internal static class NavigationSmokeTests
{
    /// <summary>旧版 2.2 仍可查看任务，但未实现页面必须保持不可操作。</summary>
    public static void Run()
    {
        var shell = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);

        SmokeAssert.True(shell.NavigationItems.Count == 10, "一级导航数量错误");
        SmokeAssert.True(
            !shell.NavigationItems
                .Single(item => item.Route == NavigationRoute.CloudDevelopment)
                .IsAvailable,
            "未实现云端开发不得可操作");
        SmokeAssert.True(
            shell.NavigationItems
                .Single(item => item.Route == NavigationRoute.TaskCenter)
                .IsAvailable,
            "2.2 任务列表必须保持可用");
    }
}
