using System.Windows;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>结果中心：通用任务结果走统一 TaskDetail；诊断额外保留固定安全卡片。</summary>
public partial class ResultsPage : System.Windows.Controls.UserControl
{
    public ResultsPage()
    {
        InitializeComponent();
    }

    private void OpenTaskDetail_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { DataContext: ResultRowViewModel result }
            || DataContext is not ResultsPageViewModel viewModel)
        {
            return;
        }

        viewModel.SelectedResult = result;
        OpenTaskDetail(result.TaskId);
    }

    private void OpenSelectedTaskDetail_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ResultsPageViewModel { SelectedResult: { } result })
        {
            MessageBox.Show(Window.GetWindow(this), "请先选择一个结果。", "查看结果", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        OpenTaskDetail(result.TaskId);
    }

    private void OpenTaskDetail(string taskId)
    {
        try
        {
            var gateway = TaskDetailGatewayContext.GetGateway(this)
                ?? throw new InvalidOperationException("任务详情服务尚未就绪。");
            TaskDetailViewModel detailViewModel = gateway.Create(taskId);
            new TaskDetailWindow(detailViewModel)
            {
                Owner = Window.GetWindow(this),
            }.Show();
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "结果详情暂时无法打开。结果和任务状态都没有被修改，请刷新后重试。",
                "无法打开结果",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
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
                "诊断安全卡片无法显示。详细信息已写入脱敏日志，结果元数据和任务状态不会被修改。",
                "读取安全卡片失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}
