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

    // 01. Generic picker and per-shot card share exactly one original
    //     snapshot staging path; neither one bypasses explicit source/rights.
    private async void ChooseReference_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanEdit) return;
        if (ShotComboBox.SelectedItem is not string shotId)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "请先选择镜头。");
            return;
        }
        await ChooseReferenceForShotAsync(shotId);
    }

    // 02. Shot-specific convenience selection does NOT assert a local Qwen
    //     observation, choose USER_SUPPLIED automatically, or grant approval.
    private async void ChooseCompositionShot_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanEdit
            || sender is not Button { Tag: ReferenceCompositionWorkItem item }
            || !vm.CompositionWorkOrders.Contains(item)
            || !vm.EligibleShots.Contains(item.ShotId, StringComparer.Ordinal)) return;
        await ChooseReferenceForShotAsync(item.ShotId);
    }

    private async Task ChooseReferenceForShotAsync(string shotId)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanEdit
            || !vm.EligibleShots.Contains(shotId, StringComparer.Ordinal)) return;
        try
        {
            // 04. No implicit original-photo classification: the operator
            //     must explicitly select a valid origin before the OS file picker.
            if (SourceComboBox.SelectedItem is not ComboBoxItem { Content: string source }
                || source is not ("USER_SUPPLIED" or "LICENSED"))
            {
                OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                    "请先在来源声明中主动选择 USER_SUPPLIED 或 LICENSED；生成图不能默认为本人原图。");
                return;
            }
            var digest = SourceDigestTextBox.Text.Trim();
            // 03. A generated/third-party picture cannot be registered as
            //     LICENSED until the operator has an explicit source digest.
            if (source == "LICENSED" && (digest.Length != 64 || digest.Any(ch =>
                !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))))
            {
                OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                    "LICENSED 图片必须先填有效的许可或来源材料 SHA-256；没有自动授予使用权。");
                return;
            }
            var picker = new Microsoft.Win32.OpenFileDialog
            {
                Filter = "参考图 (PNG, JPEG, WebP)|*.png;*.jpg;*.jpeg;*.webp",
                Multiselect = false, CheckFileExists = true,
                Title = $"选择 {shotId} 的本地参考图"
            };
            if (picker.ShowDialog() != true) return;
            await vm.AddAsync(shotId, picker.FileName, source, digest);
            // 05. Avoid accidentally carrying one shot's provenance declaration
            //     into the next shot; exact source choice is per image.
            SourceComboBox.SelectedIndex = -1;
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "参考图字节、格式或来源声明核验失败；未申请审批，也未启动 GPU。");
        }
    }

    // 03. Copy the single frozen three-shot director handoff, preserving
    //     exact per-shot prompts and cut continuity without any API/GPU call.
    private void CopyThreeShotBrief_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm
            || !vm.CanCopyFrozenThreeShotBrief) return;
        try
        {
            System.Windows.Clipboard.SetText(vm.BuildFrozenThreeShotBrief());
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "三镜头封存构图交接单已复制；图片、许可、审批和 GPU 授权仍需独立核实。");
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "剪贴板不可用；封存三镜头 Prompt 和连续性说明仍可在上方阅读。");
        }
    }

    // 04. Only copy the exact frozen Creative Kit still prompt.
    //     No local Qwen observation or approval can rewrite its text.
    private void CopyCompositionPrompt_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm
            || sender is not Button { Tag: ReferenceCompositionWorkItem item }
            || !vm.CompositionWorkOrders.Contains(item)
            || string.IsNullOrWhiteSpace(item.StillPrompt)) return;
        try
        {
            System.Windows.Clipboard.SetText(item.StillPrompt);
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "已复制封存的镜头提示词；没有提交生成任务，GPU 仍 HOLD。");
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "系统剪贴板不可用，原始镜头 Prompt 仍可在只读文本框中查看。");
        }
    }

    // 本地工作单只显示三个镜头的构图准备状态，不触发导入或审批。
    private async void LoadCompositionWorkOrder_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanLoadCompositionWorkOrder) return;
        var picker = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "三镜头工作单 (JSON)|*.json",
            Multiselect = false, CheckFileExists = true, Title = "选择本地 Qwen 三镜头 readiness 报告"
        };
        if (picker.ShowDialog() != true) return;
        try
        {
            await vm.LoadCompositionWorkOrderAsync(picker.FileName);
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText);
        }
        catch (Exception)
        {
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "工作单与封存 Creative Kit 不匹配，未导入资产或触发审批。");
        }
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
            // 01. Prefer the existing Comfy Desktop output when its actual
            //     bytes pass the ViewModel SHA and pixel validation.
            var previewReady = await PreviewObservedOutputAsync(vm);
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                previewReady ? vm.StatusText :
                    "候选清单已读取，图片尚未核验；可重新选择输出目录。未选择参考图或申请审批。");
        }
        catch (Exception)
        {
            _observedOutputRoot = null;
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, "候选清单验证失败，未导入任何图片。");
        }
    }

    // 07. Selecting one variant-root folder loads vNNNN review manifests
    //     as a single thumbnail collection. It never runs or queues Qwen.
    private async void LoadObservedVariantFolder_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanLoadObservedCandidates) return;
        var picker = new Microsoft.Win32.OpenFolderDialog
        {
            Title = "选择包含 v0000、v0001 等候选清单文件夹的目录（仅只读）"
        };
        if (picker.ShowDialog() != true) return;
        try
        {
            await vm.LoadObservedVariantFolderAsync(picker.FolderName);
            // 02. Reuse the same verified output-root lookup for every seed,
            //     rather than requiring a second picker on each import.
            var previewReady = await PreviewObservedOutputAsync(vm);
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                previewReady ? vm.StatusText :
                    "多组 seed 清单已读取，图片尚未核验；未选择参考图或申请审批。");
        }
        catch (Exception)
        {
            _observedOutputRoot = null;
            OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty,
                "多组 seed 候选清单验证失败；未导入图片、申请审批或启动 GPU。");
        }
    }

    // 03. Try exactly one standard user-local Comfy Desktop folder; do not
    //     scan drives, start Comfy, infer history, or mark a candidate licensed.
    //     ViewModel rechecks every image SHA, bounds, pixel and path on disk.
    public static async Task<string?> TryInspectStandardComfyOutputAsync(
        ReferenceBatchPreviewViewModel vm, string localAppDataRoot)
    {
        if (vm is null || !vm.CanLoadObservedCandidates
            || string.IsNullOrWhiteSpace(localAppDataRoot)
            || !Path.IsPathFullyQualified(localAppDataRoot))
            return null;
        var root = Path.Combine(localAppDataRoot, "Comfy-Desktop", "ComfyUI-Shared", "output");
        if (!Directory.Exists(root)) return null;
        try
        {
            await vm.InspectObservedCandidatesAsync(root);
            return root;
        }
        catch (InvalidDataException) { return null; }
        catch (IOException) { return null; }
        catch (UnauthorizedAccessException) { return null; }
    }

    // 04. A nonstandard or changed output remains manually selectable; a
    //     cancelled picker keeps only untrusted manifest metadata on screen.
    private async Task<bool> PreviewObservedOutputAsync(ReferenceBatchPreviewViewModel vm)
    {
        _observedOutputRoot = null;
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var verified = await TryInspectStandardComfyOutputAsync(vm, local);
        if (verified is not null)
        {
            _observedOutputRoot = verified;
            return true;
        }

        var folder = new Microsoft.Win32.OpenFolderDialog
        {
            Title = "选择 ComfyUI Output 根目录（仅本地读取并核对缩略图）"
        };
        if (folder.ShowDialog() != true) return false;
        await vm.InspectObservedCandidatesAsync(folder.FolderName);
        _observedOutputRoot = folder.FolderName;
        return true;
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
        if (System.Windows.MessageBox.Show(vm.ReviewedPlanLabel + "？此操作不启动 GPU。",
                "确认冻结生产计划", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        try { await vm.CreateReviewedPlanAsync(); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText); }
    }

    // 01. Explicit user action only. The confirmation describes the actual
    //     GPU consequence; no local gate is changed from automatic refresh.
    private async void ArmReviewedLtxJobs_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ReferenceBatchPreviewViewModel vm || !vm.CanArmReviewedLtxJobs) return;
        if (System.Windows.MessageBox.Show(
            $"放行这 {vm.CreatedLtxJobs.Count} 个已冻结镜头？运行中的本地 Worker 将使用 GPU 顺序生成；不会自动批准画面或成片。",
            "确认本地 GPU 生产", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        try { await vm.ArmReviewedLtxJobsAsync(); }
        catch (Exception) { OperationStatusText.SetCurrentValue(System.Windows.Controls.TextBlock.TextProperty, vm.StatusText); }
    }

    private void OpenApprovals_Click(object sender, RoutedEventArgs e) => ApprovalsRequested?.Invoke(this, EventArgs.Empty);
}
