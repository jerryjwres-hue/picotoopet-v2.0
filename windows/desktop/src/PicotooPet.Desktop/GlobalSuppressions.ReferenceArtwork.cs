using System.Diagnostics.CodeAnalysis;

// AssistantArtworkData 的公开 WPF 资源契约统一暴露 ImageSource；底层实际对象均为已 Freeze 的 BitmapImage。
// CA1859 只针对该类型的私有解码返回抽象提出微优化建议，不涉及正确性；限制到单一类型，避免降低项目级 Analyzer 门禁。
[assembly: SuppressMessage(
    "Performance",
    "CA1859:Use concrete types when possible",
    Justification = "保持参考美术 WPF ImageSource 资源契约稳定；底层 BitmapImage 已冻结并按需缓存。",
    Scope = "type",
    Target = "~T:PicotooPet.Desktop.Views.Controls.AssistantArtworkData")]
