using System.Windows;
using PicotooPet.Desktop.ViewModels;
using UserControl = System.Windows.Controls.UserControl;
using Button = System.Windows.Controls.Button;
using ComboBoxItem = System.Windows.Controls.ComboBoxItem;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>预览窗口仅提交待审批请求；真实批准由现有审批中心独立执行。</summary>
public partial class ReferenceBatchPreviewPanel : UserControl
{
    public event EventHandler? ApprovalsRequested;
    public ReferenceBatchPreviewPanel() => InitializeComponent();
    public ReferenceBatchPreviewPanel(ReferenceBatchPreviewViewModel viewModel) : this()
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        DataContext = viewModel;
    }

    private async void ChooseReference_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanEdit) return;
        try
        {
            if (ShotComboBox.SelectedItem is not string shotId
                || SourceComboBox.SelectedItem is not ComboBoxItem { Content: string source })
            { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "请先选择镜头和来源声明。"); return; }
            var picker = new Microsoft.Win32.OpenFileDialog
            {
                Filter = "参考图 (PNG, JPEG, WebP)|*.png;*.jpg;*.jpeg;*.webp",
                Multiselect = false, CheckFileExists = true, Title = "选择本镜头参考图"
            };
            if (picker.ShowDialog() != true) return;
            await vm.AddAsync(shotId, picker.FileName, source, SourceDigestTextBox.Text.Trim());
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "未能验证所选图片，请检查格式、大小和使用权声明。"); }
    }

    private void RemoveReference_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || sender is not Button { Tag: string shotId }) return;
        try { vm.Remove(shotId); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "该批次已锁定，无法更改参考图。"); }
    }

    private async void SubmitBatch_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm) return;
        try { await vm.SubmitAsync(); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "未取得可验证的回执；请保持当前批次并重试。"); }
    }

    private async void RefreshBatch_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm) return;
        try { await vm.RefreshAsync(); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "未能验证本地快照或 Core 回执，请稍后重试。"); }
    }

    private void OpenApprovals_Click(object sender, RoutedEventArgs e) => ApprovalsRequested?.Invoke(this, EventArgs.Empty);
}
