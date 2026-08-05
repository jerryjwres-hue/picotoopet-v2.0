using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>结果中心视图只转发显式安全预览动作。</summary>
public partial class ResultsPage : System.Windows.Controls.UserControl
{
    public ResultsPage()
    {
        InitializeComponent();
    }

    private async void LoadPreview_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ResultsPageViewModel viewModel)
        {
            return;
        }

        try
        {
            await viewModel.LoadSelectedPreviewAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "结果无法安全显示。详细信息已写入脱敏日志，结果元数据和任务状态不会被修改。",
                "读取安全预览失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}
