using System.Windows;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>Frugal Coding 仲裁的只读 WPF 面板。</summary>
public partial class CodingEscalationDecisionPanel : System.Windows.Controls.UserControl
{
    private bool _loadStarted;

    public CodingEscalationDecisionPanel()
    {
        InitializeComponent();
        DataContext = new CodingEscalationDecisionViewModel();
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadStarted)
        {
            return;
        }

        _loadStarted = true;
        var gateway = CodingEscalationDecisionGatewayContext.GetGateway(this);
        if (gateway is null)
        {
            // 独立布局 smoke 没有运行时 Session；保留只读默认投影即可。
            return;
        }
        DataContext = new CodingEscalationDecisionViewModel(gateway);
    }
}
