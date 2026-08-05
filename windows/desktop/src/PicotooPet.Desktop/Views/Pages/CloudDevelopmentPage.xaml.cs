using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10A Handoff 与 Phase 10B-A Return 验证的原生 WPF 页面。</summary>
public partial class CloudDevelopmentPage : System.Windows.Controls.UserControl
{
    private readonly ReturnValidationPanel _returnValidationPanel;
    private bool _loadStarted;

    public CloudDevelopmentPage()
    {
        InitializeComponent();
        _returnValidationPanel = new ReturnValidationPanel();
        AppendReturnValidationPanel();
    }

    private void AppendReturnValidationPanel()
    {
        if (Content is not ScrollViewer scrollViewer
            || scrollViewer.Content is not StackPanel stackPanel)
        {
            throw new InvalidOperationException(
                "Cloud Development 页面缺少固定 ScrollViewer/StackPanel 内容根。"
            );
        }
        stackPanel.Children.Add(_returnValidationPanel);
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
