using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>独立影视入口：只组合原有面板，不创建新队列或自动执行工作流。</summary>
public sealed class FilmStudioPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _assetSession;

    public FilmStudioPageViewModel(ControlCenterSession session) : base("影视工作台")
    {
        ArgumentNullException.ThrowIfNull(session);
        _assetSession = session;
        Creative = new CreativeIntelligencePanelViewModel(session)
        {
            StoryPackInitiallyExpanded = true,
        };
        Production = new ProductionPanelViewModel(session);
    }

    private FilmStudioPageViewModel() : base("影视工作台")
    {
        Creative = CreativeIntelligencePanelViewModel.CreateForSmokeTest(
            Array.Empty<CreativeEligibleSourceRecord>());
        Creative.StoryPackInitiallyExpanded = true;
        Production = ProductionPanelViewModel.CreateForSmokeTest();
    }

    // 01. 复用原有 Session、只读预览和明确确认的 Goal 操作。
    public CreativeIntelligencePanelViewModel Creative { get; }

    // 02. 复用生产面板的全部既有审批与 HOLD 限制。
    public ProductionPanelViewModel Production { get; }

    // 03. 读取真实活动项目，禁止自动创建或改写项目。
    public async Task<IReadOnlyList<ProjectRecord>> GetAssetProjectsAsync(CancellationToken cancellationToken)
    {
        var session = _assetSession ?? throw new InvalidOperationException("离线测试没有 Core 会话。");
        var projects = await session.GetProjectsAsync(cancellationToken);
        return projects.Where(project => project.Status == "Active").ToArray();
    }

    // 04. 仅显式 UI 同意后调用，登记不等于 Owner/MASTER 批准。
    public Task<string> RegisterAssetAsync(
        string projectId, string role, string mediaType, byte[] data, CancellationToken cancellationToken)
    {
        var session = _assetSession ?? throw new InvalidOperationException("离线测试没有 Core 会话。");
        return session.ImportStudioAssetAsync(projectId, role, mediaType, data, cancellationToken);
    }

    // 05. 既有 FLUX LoRA 只向 Mac 发送 Windows 核验摘要；原文件仍在 Windows。
    public Task<StudioWindowsClaimReceipt> RegisterWindowsLoraAsync(
        string projectId, string sha256, long sizeBytes,
        StudioWindowsByteEvidence evidence, CancellationToken cancellationToken)
    {
        var session = _assetSession ?? throw new InvalidOperationException("离线测试没有 Core 会话。");
        return session.RegisterStudioWindowsLoraAsync(
            projectId, sha256, sizeBytes, evidence, cancellationToken);
    }

    // 06. 这不是执行审批；必须在界面另外显示清晰的 Owner 待审批确认。
    public Task<StudioOwnerApprovalRequestReceipt> RequestAssetOwnerApprovalAsync(
        string assetId, string sha256, StudioWindowsByteEvidence? evidence,
        CancellationToken cancellationToken)
    {
        var session = _assetSession ?? throw new InvalidOperationException("离线测试没有 Core 会话。");
        return session.RequestStudioAssetOwnerApprovalAsync(
            assetId, sha256, evidence, cancellationToken);
    }

    // 同一配对会话、同一 Core，不建立新凭据或连接身份。
    internal ControlCenterSession ScopedSession => _assetSession
        ?? throw new InvalidOperationException("离线测试没有 Core 会话。");

    public static FilmStudioPageViewModel CreateForSmokeTest() => new();
}
