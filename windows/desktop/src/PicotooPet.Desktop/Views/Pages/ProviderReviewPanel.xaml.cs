using System.ComponentModel;
using System.Windows.Controls;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10D-B Return Review 只读面板。</summary>
public partial class ProviderReviewPanel : UserControl
{
    public ProviderReviewPanel()
    {
        InitializeComponent();
        if (!DesignerProperties.GetIsInDesignMode(this))
        {
            DataContext = new ProviderReviewViewModel();
        }
    }

    /// <summary>运行时注入当前安全配对会话的固定 Review gateway。</summary>
    public void SetGateway(IProviderReviewGateway gateway)
    {
        ArgumentNullException.ThrowIfNull(gateway);
        DataContext = new ProviderReviewViewModel(gateway);
    }
}
