using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10D-A 真实 Codex Provider 的独立原生 WPF 面板。</summary>
public partial class ProviderSessionPanel : System.Windows.Controls.UserControl
{
    private bool _loadStarted;

    public ProviderSessionPanel()
    {
        InitializeComponent();
        DataContext = new ProviderSessionViewModel();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadStarted)
        {
            return;
        }

        _loadStarted = true;
        var gateway = ProviderGatewayContext.GetGateway(this);
        if (gateway is null)
        {
            // 独立布局测试没有运行时 Session，继续使用确定性 smoke 安全投影。
            return;
        }

        var viewModel = new ProviderSessionViewModel(gateway);
        DataContext = viewModel;
        try
        {
            await viewModel.LoadAsync(CancellationToken.None);
        }
        catch (Exception exception)
        {
            System.Diagnostics.Trace.TraceError(
                "Provider panel initial load failed: {0}",
                exception.GetType().Name);
        }
    }
}
