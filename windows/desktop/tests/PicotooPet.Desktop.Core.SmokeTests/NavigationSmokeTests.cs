using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 26.1 五入口简单导航，同时证明历史高级页面仍可达。</summary>
internal static class NavigationSmokeTests
{
    public static void Run()
    {
        using var shell = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);

        var expected = new[] { "首页", "待我审核", "进行中", "已完成", "高级" };
        SmokeAssert.True(shell.NavigationItems.Count == expected.Length, "26.1 简单导航数量错误");
        SmokeAssert.True(
            shell.NavigationItems.Select(item => item.Title).SequenceEqual(expected),
            "26.1 简单导航顺序错误");
        SmokeAssert.True(
            shell.NavigationItems.Single(item => item.Route == NavigationRoute.OperatorHome).IsAvailable,
            "首页必须始终可打开");
        SmokeAssert.True(
            shell.NavigationItems.Single(item => item.Route == NavigationRoute.AdvancedHome).IsAvailable,
            "高级功能首页必须可打开");

        shell.Navigate(NavigationRoute.CloudDevelopment);
        var page = shell.CurrentPage as CloudDevelopmentPageViewModel;
        SmokeAssert.True(page is not null, "云端开发高级页面必须仍可到达");
        SmokeAssert.True(page!.Title == "云端开发", "云端开发标题被改写");
        SmokeAssert.True(page.ContractVersion == "1.0.0", "云端开发合同版本错误");
        SmokeAssert.True(!page.ProviderConfigured, "云端开发不得伪造 Provider 已配置");
        SmokeAssert.True(
            shell.SelectedNavigationItem.Route == NavigationRoute.AdvancedHome,
            "高级子页面打开后侧栏必须保持高级选中");

        shell.ShowNavigationFailure(NavigationRoute.TaskCenter);
        var failurePage = shell.CurrentPage as EmptyStatePageViewModel;
        SmokeAssert.True(failurePage is not null, "故障页面必须替换为安全空状态");
        SmokeAssert.True(failurePage!.Title == "任务中心暂时不可用", "高级子页面故障必须保留真实页面名");
        SmokeAssert.True(
            failurePage.Reason == "页面加载时发生故障，Control Center 已隔离该页面。",
            "故障隔离原因错误");
        SmokeAssert.True(
            shell.StatusMessage == "任务中心页面加载失败，其他页面仍可使用。",
            "Shell 未展示真实高级页面隔离状态");

        shell.Navigate(NavigationRoute.Dashboard);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.Dashboard, "页面故障后其他高级导航不可用");
        SmokeAssert.True(
            shell.SelectedNavigationItem.Route == NavigationRoute.AdvancedHome,
            "历史 Dashboard 作为高级页面打开时侧栏状态错误");

        shell.Navigate(NavigationRoute.OperatorHome);
        SmokeAssert.True(shell.CurrentRoute == NavigationRoute.OperatorHome, "返回简单首页失败");
    }
}
