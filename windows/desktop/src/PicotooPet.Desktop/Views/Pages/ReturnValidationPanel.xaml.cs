using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Phase 10B-A Return 合同验证的原生 WPF 面板。</summary>
public partial class ReturnValidationPanel : System.Windows.Controls.UserControl
{
    private bool _loadStarted;

    public ReturnValidationPanel()
    {
        InitializeComponent();
        DataContext = new ReturnValidationViewModel();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadStarted)
        {
            return;
        }

        _loadStarted = true;
        var gateway = ReturnGatewayContext.GetGateway(this);
        if (gateway is null)
        {
            // 独立布局测试没有运行时 Session，继续使用确定性 smoke 安全投影。
            return;
        }

        var viewModel = new ReturnValidationViewModel(gateway);
        DataContext = viewModel;
        try
        {
            await viewModel.LoadAsync(CancellationToken.None);
        }
        catch (Exception exception)
        {
            // 预期网络错误由 ViewModel 转成有界状态；未知加载故障只记录类型。
            System.Diagnostics.Trace.TraceError(
                "Return validation initial load failed: {0}",
                exception.GetType().Name);
        }
    }
}
