using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10B-B 固定 Mock Dev Broker 的独立原生 WPF 面板。</summary>
public partial class BrokerSessionPanel : UserControl
{
    private bool _loadStarted;

    public BrokerSessionPanel()
    {
        InitializeComponent();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (DataContext is not BrokerSessionViewModel)
        {
            var gateway = BrokerGatewayContext.GetGateway(this);
            if (gateway is null)
            {
                return;
            }
            DataContext = new BrokerSessionViewModel(gateway);
        }
        if (_loadStarted || DataContext is not BrokerSessionViewModel viewModel)
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
            // ViewModel 已处理预期网络与进程错误；这里只隔离未知 WPF 加载故障。
            System.Diagnostics.Trace.TraceError(
                "Broker panel initial load failed: {0}",
                exception.GetType().Name);
        }
    }
}
