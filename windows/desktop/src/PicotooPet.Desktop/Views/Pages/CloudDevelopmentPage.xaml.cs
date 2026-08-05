using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10A Handoff 准备、预览与审批提交的原生 WPF 页面。</summary>
public partial class CloudDevelopmentPage : System.Windows.Controls.UserControl
{
    private bool _loadStarted;

    public CloudDevelopmentPage()
    {
        InitializeComponent();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadStarted || DataContext is not CloudDevelopmentPageViewModel viewModel)
        {
            return;
        }

        _loadStarted = true;
        try
        {
            await viewModel.LoadAsync(CancellationToken.None);
        }
        catch (Exception exception)
        {
            // 页面 ViewModel 已把预期网络错误转换为有界状态；此处只隔离未知加载故障。
            System.Diagnostics.Trace.TraceError(
                "Cloud Development initial load failed: {0}",
                exception.GetType().Name);
        }
    }
}
