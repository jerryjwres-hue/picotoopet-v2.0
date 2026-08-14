using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式审核入口；复用既有摘要绑定审批中心，不建立新的审批语义。</summary>
public sealed class OperatorReviewPageViewModel : PageViewModel
{
    public OperatorReviewPageViewModel(ControlCenterSession session)
        : base("待我审核")
    {
        ApprovalCenter = new ApprovalsPageViewModel(
            session ?? throw new ArgumentNullException(nameof(session)));
    }

    private OperatorReviewPageViewModel()
        : base("待我审核")
    {
        ApprovalCenter = ApprovalsPageViewModel.CreateForSmokeTest(
            Array.Empty<PicotooPet.Desktop.Core.Contracts.ApprovalRecord>());
    }

    public ApprovalsPageViewModel ApprovalCenter { get; }

    /// <summary>解释简单模式只集中入口，不改变原审批中心摘要绑定语义。</summary>
    public string Explanation { get; } =
        "所有批准/拒绝仍由原审批中心按请求摘要执行；简单模式只把入口集中到这里。";

    public static OperatorReviewPageViewModel CreateForSmokeTest() => new();
}
