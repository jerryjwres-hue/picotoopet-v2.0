namespace PicotooPet.Desktop.Views.Pages;

/// <summary>26.1 进行中/已完成共用列表页；只渲染既有耐久任务事实。</summary>
public partial class OperatorTaskListPage : System.Windows.Controls.UserControl
{
    public OperatorTaskListPage()
    {
        PicotooPet.Desktop.Views.PicoThemeResourceLoader.Attach(this);   // 独立 WPF smoke 也必须拥有完整产品主题。
        InitializeComponent();
    }
}
