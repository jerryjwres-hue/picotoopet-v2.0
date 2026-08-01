namespace PicotooPet.Desktop.ViewModels;

/// <summary>Control Center 页面模型的最小公共表面。</summary>
public abstract class PageViewModel
{
    /// <summary>初始化页面标题。</summary>
    protected PageViewModel(string title)
    {
        Title = string.IsNullOrWhiteSpace(title)
            ? throw new ArgumentException("页面标题不能为空。", nameof(title))
            : title;
    }

    /// <summary>页面主标题。</summary>
    public string Title { get; }
}
