using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

public partial class NewTaskWizardWindow : Window
{
    private readonly NewTaskWizardViewModel _viewModel;
    private readonly CancellationTokenSource _lifetime = new();

    public NewTaskWizardWindow(NewTaskWizardViewModel viewModel)
    {
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        DataContext = _viewModel;
        InitializeComponent();
    }

    private void Back_Click(object sender, RoutedEventArgs e) => _viewModel.Back();

    private void Next_Click(object sender, RoutedEventArgs e) => _viewModel.Next();

    private async void Submit_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            if (await _viewModel.SubmitAsync(_lifetime.Token))
            {
                DialogResult = true;
            }
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // 窗口关闭时取消当前安全操作属于正常路径。
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                this,
                exception.Message,
                "任务未创建",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
    }

    protected override void OnClosed(EventArgs e)
    {
        _lifetime.Cancel();
        _lifetime.Dispose();
        base.OnClosed(e);
    }
}
