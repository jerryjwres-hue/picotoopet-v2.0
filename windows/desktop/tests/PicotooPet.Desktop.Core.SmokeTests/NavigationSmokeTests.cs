using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Control Center 一级导航、能力关闭策略和解释性文案。</summary>
internal static class NavigationSmokeTests
{
    /// <summary>旧版 2.2 仍可查看任务，但未实现页面必须保持不可操作。</summary>
    public static void Run()
    {
        var shell = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);

        SmokeAssert.True(shell.NavigationItems.Count == 11, "一级导航数量错误");
        SmokeAssert.True(
            shell.NavigationItems
                .Single(item => item.Route == NavigationRoute.CloudDevelopment)
                .IsAvailable,
            "冻结合同状态页必须可打开");
        SmokeAssert.True(
            shell.NavigationItems
                .Single(item => item.Route == NavigationRoute.TaskCenter)
                .IsAvailable,
            "2.2 任务列表必须保持可用");

        shell.Navigate(NavigationRoute.CloudDevelopment);
        var page = shell.CurrentPage as CloudDevelopmentPageViewModel;
        SmokeAssert.True(page is not null, "云端开发必须显示冻结合同状态页");
        SmokeAssert.True(page!.Title == "云端开发", "云端开发标题被改写");
        SmokeAssert.True(page.ContractVersion == "1.0.0", "云端开发合同版本错误");
        SmokeAssert.True(!page.ProviderConfigured, "云端开发不得伪造 Provider 已配置");

        shell.ShowNavigationFailure(NavigationRoute.TaskCenter);
        var failurePage = shell.CurrentPage as EmptyStatePageViewModel;
        SmokeAssert.True(failurePage is not null, "故障页面必须替换为安全空状态");
        SmokeAssert.True(failurePage!.Title == "任务中心暂时不可用", "故障回退标题错误");
        SmokeAssert.True(
            failurePage.Reason == "页面加载时发生故障，Control Center 已隔离该页面。",
            "故障隔离原因错误");
        SmokeAssert.True(
            shell.StatusMessage == "任务中心页面加载失败，其他页面仍可使用。",
            "Shell 未展示页面隔离状态");

        shell.Navigate(NavigationRoute.Dashboard);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.Dashboard, "页面故障后其他导航不可用");
    }
}
