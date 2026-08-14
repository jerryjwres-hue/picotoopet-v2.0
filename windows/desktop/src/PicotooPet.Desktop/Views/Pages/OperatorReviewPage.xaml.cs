namespace PicotooPet.Desktop.Views.Pages;

/// <summary>26.1 待我审核页面；只展示既有审批事实的简单模式投影。</summary>
public partial class OperatorReviewPage : System.Windows.Controls.UserControl
{
    public OperatorReviewPage()
    {
        PicotooPet.Desktop.Views.PicoThemeResourceLoader.Attach(this);   // 独立 WPF smoke 也必须拥有完整产品主题。
        InitializeComponent();
    }
}
