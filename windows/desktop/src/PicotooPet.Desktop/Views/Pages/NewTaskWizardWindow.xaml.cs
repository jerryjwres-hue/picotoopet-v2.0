using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>26.1 受限新任务向导窗口；关闭时会取消并释放本窗口拥有的操作令牌。</summary>
public partial class NewTaskWizardWindow : Window, IDisposable
{
    private readonly NewTaskWizardViewModel _viewModel;
    private readonly CancellationTokenSource _lifetime = new();
    private bool _disposed;

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

    /// <summary>幂等释放窗口拥有的取消令牌源，不改变任务或审批状态。</summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _lifetime.Cancel();
        _lifetime.Dispose();
        GC.SuppressFinalize(this);
    }

    protected override void OnClosed(EventArgs e)
    {
        Dispose();
        base.OnClosed(e);
    }
}
