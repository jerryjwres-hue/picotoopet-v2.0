using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Handoff / Return Contract v1 的只读展示边界。</summary>
internal static class CloudDevelopmentSmokeTests
{
    public static void Run()
    {
        var page = new CloudDevelopmentPageViewModel();

        SmokeAssert.Equal("云端开发", page.Title, "云端开发页面标题错误");
        SmokeAssert.Equal("1.0.0", page.ContractVersion, "Handoff 合同版本错误");
        SmokeAssert.Equal("Approved / Frozen", page.ContractStatus, "Handoff 合同状态错误");
        SmokeAssert.True(!page.ProviderConfigured, "当前版本不得伪造 Provider 已配置");
        SmokeAssert.True(
            page.ProviderStatus.Contains("未安装", StringComparison.Ordinal),
            "当前 Provider 状态必须明确未安装");
        SmokeAssert.Equal(9, page.TrustChain.Count, "冻结信任链必须完整显示九个阶段");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("Protected 原件", StringComparison.Ordinal)),
            "缺少 Protected 原件边界");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("本地验证", StringComparison.Ordinal)),
            "缺少本地验证边界");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("自动 push", StringComparison.Ordinal)),
            "缺少自动发布禁止项");
        SmokeAssert.Equal(3, page.PhaseMilestones.Count, "阶段状态必须覆盖 Phase 2.3、10A 和 10B");
        SmokeAssert.True(
            page.PhaseMilestones.All(milestone => !string.IsNullOrWhiteSpace(milestone.Status)),
            "阶段状态不得为空");
    }
}
