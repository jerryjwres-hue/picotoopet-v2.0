using System.Drawing;
using System.Windows.Forms;

namespace PicotooPet.Desktop.Services;

/// <summary>使用 Windows Forms 内置 NotifyIcon 提供轻量托盘生命周期。</summary>
public sealed class WindowsTrayService : ITrayService
{
    private readonly ContextMenuStrip _contextMenu;
    private readonly NotifyIcon _notifyIcon;
    private bool _disposed;

    /// <summary>创建托盘图标和打开、审批、显式退出命令。</summary>
    public WindowsTrayService()
    {
        var openItem = new ToolStripMenuItem("打开控制中心");
        openItem.Click += OnOpenClicked;

        var approvalsItem = new ToolStripMenuItem("待审批");
        approvalsItem.Click += OnPendingApprovalsClicked;

        var pauseAutomationItem = new ToolStripMenuItem("暂停自动化（能力未启用）")
        {
            Enabled = false,
            ToolTipText = "当前 Slice A 尚未声明自动化暂停能力。",
        };
        var gameModeItem = new ToolStripMenuItem("游戏模式（能力未启用）")
        {
            Enabled = false,
            ToolTipText = "当前 Slice A 尚未声明游戏模式能力。",
        };

        var exitItem = new ToolStripMenuItem("退出 UI");
        exitItem.Click += OnExitClicked;

        _contextMenu = new ContextMenuStrip();
        _contextMenu.Items.AddRange(
        [
            openItem,
            approvalsItem,
            new ToolStripSeparator(),
            pauseAutomationItem,
            gameModeItem,
            new ToolStripSeparator(),
            exitItem,
        ]);

        _notifyIcon = new NotifyIcon
        {
            ContextMenuStrip = _contextMenu,
            Icon             = SystemIcons.Application,
            Text             = "Picotoo Pet AI Control Center",
            Visible          = true,
        };
        _notifyIcon.DoubleClick += OnOpenClicked;
    }

    /// <inheritdoc />
    public event EventHandler? OpenRequested;

    /// <inheritdoc />
    public event EventHandler? PendingApprovalsRequested;

    /// <inheritdoc />
    public event EventHandler? ExitRequested;

    private void OnOpenClicked(object? sender, EventArgs e) =>
        OpenRequested?.Invoke(this, EventArgs.Empty);

    private void OnPendingApprovalsClicked(object? sender, EventArgs e) =>
        PendingApprovalsRequested?.Invoke(this, EventArgs.Empty);

    private void OnExitClicked(object? sender, EventArgs e) =>
        ExitRequested?.Invoke(this, EventArgs.Empty);

    /// <summary>隐藏托盘图标并释放菜单和原生窗口句柄。</summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _notifyIcon.DoubleClick -= OnOpenClicked;
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        _contextMenu.Dispose();
    }
}
