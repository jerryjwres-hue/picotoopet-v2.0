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

        shell.Navigate(NavigationRoute.CloudDevelopment);
        var page = shell.CurrentPage as EmptyStatePageViewModel;
        SmokeAssert.True(page is not null, "云端开发必须显示解释性空状态");
        SmokeAssert.True(page!.Title == "云端开发", "云端开发标题被改写");
        SmokeAssert.True(
            page.Reason == "当前版本只冻结了 Handoff / Return Contract，尚未安装或调用外部 Provider。",
            "云端开发原因说明被改写");
        SmokeAssert.True(
            page.NextStep == "Phase 10A 将先加入包预览和审批；Phase 10B 才加入 Dev Broker。",
            "云端开发后续步骤被改写");
        SmokeAssert.True(page.UserAction == "你现在不需要操作。", "用户动作说明被改写");
    }
}
