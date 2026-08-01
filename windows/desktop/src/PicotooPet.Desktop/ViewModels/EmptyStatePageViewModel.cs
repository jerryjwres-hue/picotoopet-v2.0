namespace PicotooPet.Desktop.ViewModels;

/// <summary>解释功能状态、下一系统步骤和用户动作的统一空状态页面。</summary>
public sealed class EmptyStatePageViewModel : PageViewModel
{
    /// <summary>创建带完整解释链的空状态。</summary>
    public EmptyStatePageViewModel(
        string title,
        string reason,
        string nextStep,
        string userAction)
        : base(title)
    {
        Reason     = RequireText(reason, nameof(reason));
        NextStep   = RequireText(nextStep, nameof(nextStep));
        UserAction = RequireText(userAction, nameof(userAction));
    }

    /// <summary>当前不可用或尚未接入的原因。</summary>
    public string Reason { get; }

    /// <summary>系统后续将执行的明确步骤。</summary>
    public string NextStep { get; }

    /// <summary>用户当前是否需要采取行动。</summary>
    public string UserAction { get; }

    private static string RequireText(string value, string parameterName) =>
        string.IsNullOrWhiteSpace(value)
            ? throw new ArgumentException("空状态说明不能为空。", parameterName)
            : value;
}
