namespace PicotooPet.Desktop.ViewModels;

/// <summary>云端开发路线的只读阶段说明。</summary>
public sealed record CloudDevelopmentMilestone(
    string Phase,
    string Status,
    string Description);

/// <summary>展示冻结的 Handoff / Return Contract，不配置或调用任何外部 Provider。</summary>
public sealed class CloudDevelopmentPageViewModel : PageViewModel
{
    private static readonly IReadOnlyList<string> FrozenTrustChain = new string[]
    {
        "Mac Handoff Manager",
        "Approval Center",
        "Windows Dev Broker",
        "Provider Adapter",
        "Isolated Worktree / Sandbox",
        "Return Package",
        "Local Validation",
        "Human Review",
        "PR / Merge / Release Approval",
    };

    private static readonly IReadOnlyList<string> FrozenSecurityBoundaries = new string[]
    {
        "Protected 原件不得进入 Handoff Package，也不得上传给 Provider。",
        "Provider 返回内容默认不可信，必须通过本地验证和人工评审。",
        "禁止自动 push、merge、tag 或 release；发布需要独立人工批准。",
        "Provider 不得直接编辑 main 或 protected branch，也不得访问未批准目录。",
        "密钥不得写入命令行、Package、日志或返回文件。",
    };

    private static readonly IReadOnlyList<CloudDevelopmentMilestone> FrozenMilestones =
        new CloudDevelopmentMilestone[]
        {
            new(
                "Phase 2.3",
                "当前：合同已冻结",
                "提供 Handoff / Return Contract v1 只读状态页；不安装、不配置、不调用 Provider。"),
            new(
                "Phase 10A",
                "未实施",
                "未来实现 Handoff 准备、包预览、摘要绑定和显式审批。"),
            new(
                "Phase 10B",
                "未实施",
                "未来实现 Windows Dev Broker、隔离 Provider 会话、事件流和 Return 本地校验。"),
        };

    public CloudDevelopmentPageViewModel()
        : base("云端开发")
    {
    }

    public string ContractVersion => "1.0.0";

    public string ContractStatus => "Approved / Frozen";

    public bool ProviderConfigured => false;

    public string ProviderStatus => "Provider 未安装、未配置、未调用。";

    public string CurrentDelivery => "当前仅展示冻结合同与安全边界，用户无需配置外部服务。";

    public IReadOnlyList<string> TrustChain => FrozenTrustChain;

    public IReadOnlyList<string> SecurityBoundaries => FrozenSecurityBoundaries;

    public IReadOnlyList<CloudDevelopmentMilestone> PhaseMilestones => FrozenMilestones;
}
