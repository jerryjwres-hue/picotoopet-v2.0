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
    private string? _observedOutputRoot;
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

    private async void LoadObservedCandidates_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanLoadObservedCandidates) return;
        var picker = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "候选清单 (JSON)|candidate_manifest.json|JSON 文件|*.json",
            Multiselect = false, CheckFileExists = true, Title = "选择本地首帧候选清单"
        };
        if (picker.ShowDialog() != true) return;
        try
        {
            await vm.LoadObservedCandidatesAsync(picker.FileName);
            _observedOutputRoot = null;
            // 01. 同一目录只选一次，后台依次重核并显示各镜头缩略图。
            var folder = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "选择当前 ComfyUI Output 根目录（只读取缩略图）"
            };
            if (folder.ShowDialog() == true)
            {
                await vm.InspectObservedCandidatesAsync(folder.FolderName);
                _observedOutputRoot = folder.FolderName;
            }
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception)
        {
            _observedOutputRoot = null;
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "候选清单验证失败，未导入任何图片。");
        }
    }

    private async void UseObservedCandidate_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanEdit
            || sender is not Button { Tag: ReferenceObservedCandidate candidate }) return;
        var licenseDigest = SourceDigestTextBox.Text.Trim();
        if (licenseDigest.Length != 64)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "本地生成图像请先输入 LICENSED 许可或来源证明的 64 位 SHA-256；不能自动视为 USER_SUPPLIED。");
            return;
        }
        if (_observedOutputRoot is null)
        {
            var folder = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "选择当前 ComfyUI Output 根目录（本地只读）"
            };
            if (folder.ShowDialog() != true) return;
            _observedOutputRoot = folder.FolderName;
        }
        try
        {
            // 01. 用户点击才导入现有快照管线；最终授权仍是独立勾选与审批。
            await vm.AddObservedCandidateAsync(candidate, _observedOutputRoot, licenseDigest);
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "候选图像、路径或来源摘要核验失败；未自动提交审批。");
        }
    }

    private async void RestoreReferenceBatch_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanResumeReferenceBatch) return;
        try
        {
            // 01. 只向现有 Core GET 查验审批，不触发 POST、Owner 决定或 GPU。
            await vm.ResumeReferenceBatchAsync(ResumeApprovalIdTextBox.Text.Trim());
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "原审批或本地参考快照无法验证；未恢复，也没有重复申请。");
        }
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

    private async void CreateReviewedPlan_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanCreateReviewedPlan) return;
        // 独立显式操作：不会由收到 Approved 回执自动触发。
        if (System.Windows.MessageBox.Show("创建与当前三张已批参考图绑定的生产计划？此操作不启动 GPU。",
                "确认三镜头生产计划", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        try { await vm.CreateReviewedPlanAsync(); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText); }
    }

    private void OpenApprovals_Click(object sender, RoutedEventArgs e) => ApprovalsRequested?.Invoke(this, EventArgs.Empty);
}
