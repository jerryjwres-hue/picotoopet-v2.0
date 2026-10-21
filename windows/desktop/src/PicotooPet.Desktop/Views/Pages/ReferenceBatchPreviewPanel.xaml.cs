using WpfUserControl = System.Windows.Controls.UserControl;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

public partial class ReferenceBatchPreviewPanel : WpfUserControl
{
    public event EventHandler? ApprovalsRequested { add { } remove { } }
    public ReferenceBatchPreviewPanel() => InitializeComponent();
    public ReferenceBatchPreviewPanel(ReferenceBatchPreviewViewModel viewModel) : this() => DataContext = viewModel;
}
