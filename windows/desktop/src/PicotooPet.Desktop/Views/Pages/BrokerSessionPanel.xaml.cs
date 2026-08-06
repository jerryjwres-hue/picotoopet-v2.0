using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10B-B 固定 Mock Dev Broker 的独立原生 WPF 面板。</summary>
public partial class BrokerSessionPanel : System.Windows.Controls.UserControl
{
    private bool _loadStarted;

    public BrokerSessionPanel()
    {
        InitializeComponent();
        DataContext = new BrokerSessionViewModel();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadStarted)
        {
            return;
        }

        _loadStarted = true;
        var gateway = BrokerGatewayContext.GetGateway(this);
        if (gateway is null)
        {
            // 独立布局测试没有运行时 Session，继续使用确定性 smoke 安全投影。
            return;
        }

        var viewModel = new BrokerSessionViewModel(gateway);
        DataContext = viewModel;
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
