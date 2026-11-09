using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.OwnerReview;
using PicotooPet.Desktop.ViewModels;
using WpfClipboard = System.Windows.Clipboard;
using WpfTextDataFormat = System.Windows.TextDataFormat;
using WpfSaveFileDialog = Microsoft.Win32.SaveFileDialog;
using WpfUserControl = System.Windows.Controls.UserControl;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>原生 Goal Center 交互层；不持有令牌，不自行创建 Workflow/Task。</summary>
public partial class GoalCenterPanel : WpfUserControl
{
    private readonly DispatcherTimer _refreshTimer;
    private bool _refreshing;
    private ReferenceBatchPreviewViewModel? _referencePreview;
    private string? _referencePreviewContext;
    private Window? _referencePreviewWindow;
    private bool _openingReferences;
    private Window? _ownerReviewLockedWindow;

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

    private void GoalCenterPanel_Unloaded(object sender, RoutedEventArgs e)
    {
        _refreshTimer.Stop();
        // A detached Goal Center must not leave an unaffiliated review window open.
        _ownerReviewLockedWindow?.Close();
        _ownerReviewLockedWindow = null;
    }

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

    private async void PasteGoalVideoReturn_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel
            || !viewModel.VideoContinuation.CanSubmit)
        {
            return;
        }

        try
        {
            var text = WpfClipboard.ContainsText(WpfTextDataFormat.UnicodeText)
                ? WpfClipboard.GetText(WpfTextDataFormat.UnicodeText)
                : string.Empty;
            var payload = GoalVideoReturnParser.Parse(text);
            await viewModel.VideoContinuation.SubmitAsync(payload).ConfigureAwait(true);
            var message = !string.IsNullOrWhiteSpace(viewModel.VideoContinuation.ErrorMessage)
                ? viewModel.VideoContinuation.ErrorMessage
                : "Web GPT 返回已由 Mac Core 校验并进入 Creative/Production 续接。";
            MessageBox.Show(
                Window.GetWindow(this),
                message,
                "Web GPT 返回",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (GoalVideoReturnParseException)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "剪贴板内容不是有效的有界 GPT 返回 JSON，或超过 512 KiB。",
                "无法提交返回",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private async void OpenFinalVideo_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel
            || !viewModel.VideoContinuation.CanOpenFinalVideo)
        {
            return;
        }

        // ViewModel owns the in-flight guard and updates the existing IsEnabled binding.
        // Never set Button.IsEnabled directly: that would replace the WPF binding expression.
        var opened = await viewModel.VideoContinuation.OpenFinalVideoAsync().ConfigureAwait(true);
        if (!opened && ReferenceEquals(DataContext, viewModel))
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "最终视频暂时无法打开；请稍后重试。",
                "无法打开最终视频",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private void AdvancedTask_Click(object sender, RoutedEventArgs e) =>
        AdvancedTaskRequested?.Invoke(this, EventArgs.Empty);

    /// <summary>
    /// The real Owner Review UI is discoverable; no review credential, transport,
    /// Core client, source data, approval or Goal action is constructed here.
    /// </summary>
    private void OwnerReviewLockedPreview_Click(object sender, RoutedEventArgs e)
    {
        if (_ownerReviewLockedWindow is { IsVisible: true })
        {
            _ownerReviewLockedWindow.Activate();
            return;
        }

        // Default (and the only reachable state while PinnedSshStdioActivated is false): the
        // noninteractive preview below. Live wiring needs the separately reviewed activation gate,
        // an owner-authored protected SSH profile and the typed pinned factory; it never uses the
        // device Bearer token, a Worker identity, Mock or plain HTTP. Nothing runs at startup.
        var credentials = new DpapiOwnerReviewCredentialStore();
        var live = OwnerReviewLiveWiring.TryOpen(credentials);
        if (live.IsOpen)
        {
            ShowLiveOwnerReview(live.Client!, credentials);
            return;
        }

        var warning = new TextBlock
        {
            Text = "安全门禁：Windows→Mac 加密审核通道与主人凭据尚未验收。此窗口仅展示界面，不能填写真实凭据、加载资料、预览或提交。生产 Core、Goal、Ollama 和 GPU 均不会被访问。（" + live.LockCode + "）",
            FontSize = 13,
            FontWeight = FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(14, 12, 14, 10),
        };
        var panel = new OwnerReviewPanel { IsEnabled = false, DataContext = null };
        var content = new DockPanel();
        DockPanel.SetDock(warning, Dock.Top);
        content.Children.Add(warning);
        content.Children.Add(panel);

        var window = new Window
        {
            Owner = Window.GetWindow(this),
            Title = "主人资料审核 · 安全连接未开放（仅界面预览）",
            Width = 980,
            Height = 740,
            MinWidth = 720,
            MinHeight = 520,
            Content = content,
        };
        window.Closed += (_, _) =>
        {
            if (ReferenceEquals(_ownerReviewLockedWindow, window))
            {
                _ownerReviewLockedWindow = null;
            }
        };
        _ownerReviewLockedWindow = window;
        window.Show();
    }

    /// <summary>Interactive window over a pinned-SSH-stdio client; the client dies with the window.</summary>
    private void ShowLiveOwnerReview(OwnerReviewClient client, IOwnerReviewCredentialStore credentials)
    {
        var viewModel = new OwnerReviewViewModel(client, credentials, livePinnedSsh: true);
        var window = new Window
        {
            Owner = Window.GetWindow(this),
            Title = "主人资料审核 · 固定主机密钥的 SSH 安全通道",
            Width = 980,
            Height = 740,
            MinWidth = 720,
            MinHeight = 520,
            Content = new OwnerReviewPanel { DataContext = viewModel },
        };
        window.Closed += (_, _) =>
        {
            client.Dispose();
            if (ReferenceEquals(_ownerReviewLockedWindow, window))
            {
                _ownerReviewLockedWindow = null;
            }
        };
        _ownerReviewLockedWindow = window;
        window.Show();
    }

    private async void ReferenceBatchPreview_Click(object sender, RoutedEventArgs e)
    {
        if (_openingReferences || DataContext is not OperatorHomePageViewModel viewModel) return;
        var context = viewModel.CurrentGoal?.GoalId + ":" + viewModel.VideoContinuation.Continuation?.CreativePackageDigest;
        if (_referencePreviewWindow is { IsVisible: true } && context == _referencePreviewContext)
        { _referencePreviewWindow.Activate(); return; }
        _referencePreviewWindow?.Close();
        _openingReferences = true;
        try
        {
            if (_referencePreview is null || context != _referencePreviewContext)
            {
                _referencePreview = await viewModel.CreateReferenceBatchPreviewAsync().ConfigureAwait(true);
                _referencePreviewContext = context;
            }
            if (!ReferenceEquals(DataContext, viewModel)) return;
            var panel = new ReferenceBatchPreviewPanel(_referencePreview);
            var window = new Window
            {
                Owner = Window.GetWindow(this), Title = "参考图 · 批量预览与审批",
                Width = 1040, Height = 760, MinWidth = 720, MinHeight = 520, Content = panel,
            };
            panel.ApprovalsRequested += (_, _) =>
            {
                if (Window.GetWindow(this) is Views.ShellWindow shell)
                {
                    window.Close(); // An owned preview window otherwise stays above the existing approvals page.
                    shell.NavigateFromOperator(Navigation.NavigationRoute.Approvals);
                    shell.Activate();
                }
            };
            window.Closed += (_, _) => _referencePreviewWindow = null;
            _referencePreviewWindow = window;
            window.Show(); // Non-modal: existing Approvals remains the separate human decision authority.
        }
        catch (Exception)
        {
            MessageBox.Show(Window.GetWindow(this),
                "参考图预览暂不可用。需要已配对 Mac Core、冻结且 PASS 的 I2V 创意包，以及现有 ComfyUI 输入目录。请刷新后重试；不会启动 GPU。",
                "参考图预览", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        finally { _openingReferences = false; }
    }
}
