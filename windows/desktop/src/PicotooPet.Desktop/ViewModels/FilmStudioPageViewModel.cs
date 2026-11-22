using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>独立影视入口：只组合原有面板，不创建新队列或自动执行工作流。</summary>
public sealed class FilmStudioPageViewModel : PageViewModel
{
    public FilmStudioPageViewModel(ControlCenterSession session) : base("影视工作台")
    {
        ArgumentNullException.ThrowIfNull(session);
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

    public static FilmStudioPageViewModel CreateForSmokeTest() => new();
}
