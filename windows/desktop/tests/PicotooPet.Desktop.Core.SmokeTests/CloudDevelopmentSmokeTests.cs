using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证冻结合同仍完整显示，同时 Phase 10A 只开放准备与审批。</summary>
internal static class CloudDevelopmentSmokeTests
{
    public static void Run()
    {
        var page = new CloudDevelopmentPageViewModel();

        SmokeAssert.Equal("云端开发", page.Title, "云端开发页面标题错误");
        SmokeAssert.Equal("1.0.0", page.ContractVersion, "Handoff 合同版本错误");
        SmokeAssert.Equal(
            "Approved / Frozen",
            page.ContractStatus,
            "Handoff 合同状态错误");
        SmokeAssert.True(
            !page.ProviderConfigured,
            "Phase 10A 不得伪造 Provider 已配置");
        SmokeAssert.Equal(9, page.TrustChain.Count, "冻结信任链必须完整显示九个阶段");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("Protected 原件", StringComparison.Ordinal)),
            "缺少 Protected 边界");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("本地验证", StringComparison.Ordinal)),
            "缺少本地复验边界");
        SmokeAssert.True(
            page.SecurityBoundaries.Any(value =>
                value.Contains("自动 push", StringComparison.Ordinal)),
            "缺少自动发布禁止项");
        SmokeAssert.True(
            page.PhaseMilestones.Any(value =>
                value.Phase == "Phase 10A" && value.Status == "当前可用"),
            "缺少 Phase 10A 当前可用状态");
        SmokeAssert.True(
            page.PhaseMilestones.Any(value =>
                value.Phase == "Phase 10B" && value.Status == "未实施"),
            "Phase 10B 必须保持未实施");
        SmokeAssert.True(
            page.ProviderStatus.Contains("未安装", StringComparison.Ordinal),
            "页面必须明确 Provider 未安装");
        SmokeAssert.True(
            page.CurrentDelivery.Contains("Phase 10A", StringComparison.Ordinal)
            && page.CurrentDelivery.Contains("审批", StringComparison.Ordinal),
            "页面必须明确当前只交付准备和审批");
        SmokeAssert.Equal(1, page.TemplateOptions.Count, "Smoke 页面固定模板数量错误");
        SmokeAssert.True(!page.CanPrepare, "空输入不得启用准备动作");
    }
}
