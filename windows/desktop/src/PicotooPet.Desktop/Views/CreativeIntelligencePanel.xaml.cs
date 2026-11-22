using System.IO;
using System.Text;
using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Creative Intelligence 只转发固定安全动作。</summary>
public partial class CreativeIntelligencePanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public CreativeIntelligencePanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not CreativeIntelligencePanelViewModel viewModel)
        {
            return;
        }
        _loadedOnce = true;
        try
        {
            await viewModel.RefreshAsync(CancellationToken.None);
        }
        catch (InvalidOperationException)
        {
            // Smoke-test ViewModel intentionally has no live Session.
        }
        catch (Exception)
        {
            ShowSafeError("创意智能读取失败", "Creative Intelligence 状态暂时无法读取；详细信息由应用脱敏日志记录。");
        }
    }

    private async void Prepare_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.PrepareAsync(CancellationToken.None));

    // 只把真实故事示例写入内存文本框；用户须再次主动点击只读检查。
    private void LoadMaotaiPilot_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is CreativeIntelligencePanelViewModel viewModel)
        {
            viewModel.LoadMaotaiDinnerPilotDraft();
        }
    }

    // 只读取用户显式选择的有界 JSON 文件；仍须手动点击只读检查。
    private void LoadStoryPackFile_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel)
        {
            return;
        }
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "StoryPack JSON (*.json)|*.json",
            CheckFileExists = true,
            Multiselect = false,
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }
        try
        {
            using var stream = new FileStream(dialog.FileName, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (stream.Length is <= 0 or > 128 * 1024)
            {
                throw new InvalidDataException("StoryPack size");
            }
            var data = new byte[(int)stream.Length];
            stream.ReadExactly(data);
            if (stream.ReadByte() != -1)
            {
                throw new InvalidDataException("StoryPack changed");
            }
            var draft = new UTF8Encoding(false, true).GetString(data).TrimStart('\uFEFF');
            if (draft.Length > 100000 || string.IsNullOrWhiteSpace(draft))
            {
                throw new InvalidDataException("StoryPack text");
            }
            viewModel.StoryPackJson = draft;
        }
        catch (Exception)
        {
            // 失败保留原草稿，不回显文件路径、内容或错误堆栈。
            ShowSafeError("StoryPack 文件读取失败", "请选择有效 UTF-8 JSON 文件（最多 128 KiB、100000 字符）。原草稿保持不变。");
        }
    }

    // 仅用户点击时请求已经存在的 Mac Core 只读入口；不持有生产授权。
    private async void StoryPackPreview_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel)
        {
            return;
        }
        try
        {
            await viewModel.PreviewStoryPackAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            // 故障文本不能泄露剧本、用户资产路径或 Bearer；生产状态仍保持 HOLD。
            ShowSafeError("StoryPack 只读预览失败", "校验未完成，未创建生产任务。");
        }
    }

    // 创建的是正式 Core Human Goal，不是生产授权；用户必须二次确认。
    private async void CreateStoryGoal_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel
            || !viewModel.CanCreateStoryGoal)
        {
            return;
        }
        var response = MessageBox.Show(
            Window.GetWindow(this),
            "将已检查的三镜头故事交给现有 Mac Core 创建本地视频创意 Goal？"
            + "\n这会启动正常的来源研究与创意工作流。"
            + "\n不会批准角色资产、生产计划、Owner 或 GPU；所有 HOLD 继续有效。",
            "确认创建本地创意 Goal",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question,
            MessageBoxResult.No);
        if (response != MessageBoxResult.Yes)
        {
            return;
        }
        try
        {
            await viewModel.CreateStoryGoalAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError("创建 Goal 失败", "Core 未确认创建成功，请检查连接后重试；GPU HOLD 保持不变。");
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel || viewModel.SelectedJob is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "取消所选 Creative Job？\n\n只取消 PicotooPet 创意任务，不删除来源 Result Package。",
            "确认取消 Creative Job",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async void ExportPackage_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ExportSelectedPackageAsync(CancellationToken.None));

    private async void ExportHandoff_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ExportSelectedHandoffAsync(CancellationToken.None));

    private async Task RunAsync(Func<CreativeIntelligencePanelViewModel, Task> action)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel)
        {
            return;
        }
        try
        {
            await action(viewModel);
        }
        catch (Exception)
        {
            ShowSafeError("创意智能操作失败", "操作未完成；不会调用付费 AI 或执行 ComfyUI，详细信息由应用脱敏日志记录。");
        }
    }

    private void ShowSafeError(string title, string message) =>
        MessageBox.Show(
            Window.GetWindow(this),
            message,
            title,
            MessageBoxButton.OK,
            MessageBoxImage.Error);
}
