using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop;

/// <summary>主窗口只处理 PasswordBox 和窗口生命周期等视图专属事件。</summary>
public partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel;

    /// <summary>绑定主视图模型。</summary>
    public MainWindow(MainWindowViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        Closed += OnClosed;
    }

    private async void SaveAndConnect_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await _viewModel.SaveAndConnectAsync(
                TokenPasswordBox.Password,
                CancellationToken.None);
            TokenPasswordBox.Clear();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                this,
                exception.Message,
                "连接失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    private async void OnClosed(object? sender, EventArgs e)
    {
        await _viewModel.DisposeAsync();
    }
}
