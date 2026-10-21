using WpfUserControl = System.Windows.Controls.UserControl;
using PicotooPet.Desktop.ViewModels;

#pragma warning disable CA1822 // Compile-only RED event scaffold; replaced by the real handler after behavioral RED.

namespace PicotooPet.Desktop.Views.Pages;

public partial class ReferenceBatchPreviewPanel : WpfUserControl
{
    public event EventHandler? ApprovalsRequested { add { } remove { } }
    public ReferenceBatchPreviewPanel() => InitializeComponent();
    public ReferenceBatchPreviewPanel(ReferenceBatchPreviewViewModel viewModel) : this() => DataContext = viewModel;
}
