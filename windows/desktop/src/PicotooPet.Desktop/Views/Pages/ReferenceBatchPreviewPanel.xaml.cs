using System.Windows.Controls;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

public partial class ReferenceBatchPreviewPanel : UserControl
{
    public event EventHandler? ApprovalsRequested;
    public ReferenceBatchPreviewPanel() => InitializeComponent();
    public ReferenceBatchPreviewPanel(ReferenceBatchPreviewViewModel viewModel) : this() => DataContext = viewModel;
}
