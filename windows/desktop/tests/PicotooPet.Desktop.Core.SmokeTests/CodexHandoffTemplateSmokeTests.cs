using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>确保 Windows Handoff 创建面同时保留旧 manual 模板并公开受控 Codex 模板。</summary>
internal static class CodexHandoffTemplateSmokeTests
{
    public static async Task RunAsync()
    {
        var page = new CloudDevelopmentPageViewModel(new TemplateGateway());
        await page.LoadAsync(CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.Equal(2, page.TemplateOptions.Count, "Windows 必须同时展示 manual 与 Codex 固定模板");
        SmokeAssert.Equal(
            "picotoopet-repo-maintenance-v1",
            page.SelectedTemplate?.TemplateId,
            "旧 manual 模板必须继续作为兼容默认项");
        SmokeAssert.True(
            page.TemplateOptions.Any(item =>
                item.TemplateId == "picotoopet-repo-maintenance-codex-v1"
                && item.Provider == "codex"),
            "受控 Codex Handoff 模板未暴露给 Windows 原生创建面");
    }

    private sealed class TemplateGateway : IHandoffGateway
    {
        public Task<HandoffTemplateRecord[]> GetTemplatesAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new[]
            {
                new HandoffTemplateRecord(
                    "picotoopet-repo-maintenance-v1",
                    "PicotooPet 仓库维护",
                    "manual",
                    ProviderConfigured: false,
                    "https://github.com/jerryjwres-hue/picotoopet-v2.0",
                    "feature/phase23-slice-d-diagnostic-snapshot-release",
                    new string('a', 40)),
                new HandoffTemplateRecord(
                    "picotoopet-repo-maintenance-codex-v1",
                    "PicotooPet Codex 仓库维护",
                    "codex",
                    ProviderConfigured: false,
                    "https://github.com/jerryjwres-hue/picotoopet-v2.0",
                    "feature/phase10c-event-stream-recovery",
                    new string('b', 40)),
            });

        public Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken) =>
            Task.FromResult(Array.Empty<HandoffRecord>());

        public Task<HandoffRecord> PrepareAsync(
            HandoffPrepareRequest request,
            string idempotencyKey,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<HandoffRecord> SubmitApprovalAsync(
            string handoffId,
            string idempotencyKey,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();
    }
}
