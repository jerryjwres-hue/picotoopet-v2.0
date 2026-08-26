using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using WpfClipboard = System.Windows.Clipboard;
using WpfSaveFileDialog = Microsoft.Win32.SaveFileDialog;
using WpfUserControl = System.Windows.Controls.UserControl;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>原生 Goal Center 交互层；不持有令牌，不自行创建 Workflow/Task。</summary>
public partial class GoalCenterPanel : WpfUserControl
{
    private readonly DispatcherTimer _refreshTimer;
    private bool _refreshing;

    public GoalCenterPanel()
    {
        InitializeComponent();
        _refreshTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(5),
        };
        _refreshTimer.Tick += RefreshTimer_Tick;
        Loaded += GoalCenterPanel_Loaded;
        Unloaded += GoalCenterPanel_Unloaded;
    }

    /// <summary>保留原有传统任务向导为次级入口。</summary>
    public event EventHandler? AdvancedTaskRequested;

    private async void GoalCenterPanel_Loaded(object sender, RoutedEventArgs e)
    {
        await RefreshNowAsync().ConfigureAwait(true);
        _refreshTimer.Start();
    }

    private void GoalCenterPanel_Unloaded(object sender, RoutedEventArgs e) => _refreshTimer.Stop();

    private async void RefreshTimer_Tick(object? sender, EventArgs e) =>
        await RefreshNowAsync().ConfigureAwait(true);

    private async Task RefreshNowAsync()
    {
        if (_refreshing || DataContext is not OperatorHomePageViewModel viewModel)
        {
            return;
        }

        _refreshing = true;
        try
        {
            await viewModel.RefreshGoalsAsync().ConfigureAwait(true);
        }
        finally
        {
            _refreshing = false;
        }
    }

    private void GoalTemplate_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is OperatorHomePageViewModel viewModel
            && sender is System.Windows.Controls.Button { DataContext: GoalTemplateRecord template })
        {
            viewModel.SelectGoalTemplate(template);
            GoalObjectiveTextBox.Focus();
            GoalObjectiveTextBox.CaretIndex = GoalObjectiveTextBox.Text.Length;
        }
    }

    private async void CreateGoal_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel)
        {
            return;
        }

        await viewModel.CreateGoalAsync().ConfigureAwait(true);
    }

    private async void CopyPrompt_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel || !viewModel.HandoffReady)
        {
            return;
        }

        try
        {
            var prompt = await viewModel.GetCurrentHandoffPromptAsync().ConfigureAwait(true);
            WpfClipboard.SetText(prompt);
            MessageBox.Show(
                Window.GetWindow(this),
                "固定 Web GPT 提示词已复制。把交接 ZIP 和这段提示词一起手动发送给网页 ChatGPT。",
                "提示词已复制",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "提示词暂时无法读取。交接包和目标事实没有被修改，请稍后重试。",
                "无法复制提示词",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private async void SaveHandoff_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel
            || viewModel.CurrentHandoff is not { HandoffReady: true } handoff)
        {
            return;
        }

        var suggestedName = Path.GetFileName(handoff.PackageName);
        if (string.IsNullOrWhiteSpace(suggestedName)
            || !suggestedName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
        {
            suggestedName = "PicotooPet-Web-GPT-Handoff.zip";
        }

        var dialog = new WpfSaveFileDialog
        {
            Title = "保存 Web GPT 交接包",
            FileName = suggestedName,
            DefaultExt = ".zip",
            Filter = "ZIP 交接包 (*.zip)|*.zip",
            AddExtension = true,
            OverwritePrompt = true,
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }

        try
        {
            var bytes = await viewModel.DownloadCurrentHandoffAsync().ConfigureAwait(true);
            await File.WriteAllBytesAsync(dialog.FileName, bytes).ConfigureAwait(true);
            MessageBox.Show(
                Window.GetWindow(this),
                "交接 ZIP 已保存。程序不会自动登录或上传到网页 ChatGPT。",
                "交接包已保存",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "交接包暂时无法保存。目标事实没有被修改，请检查磁盘权限后重试。",
                "无法保存交接包",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private void AdvancedTask_Click(object sender, RoutedEventArgs e) =>
        AdvancedTaskRequested?.Invoke(this, EventArgs.Empty);
}
