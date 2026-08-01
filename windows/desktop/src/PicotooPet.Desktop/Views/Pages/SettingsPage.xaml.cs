using System.Windows.Controls;
using System.Windows.Input;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>设置视图只声明路由命令；PasswordBox 内容由 Shell 视图转交 Session。</summary>
public partial class SettingsPage : UserControl
{
    /// <summary>请求 Shell 保存当前地址和 PasswordBox 令牌。</summary>
    public static RoutedCommand SaveAndConnectCommand { get; } = new(
        nameof(SaveAndConnectCommand),
        typeof(SettingsPage));

    /// <summary>初始化设置视图。</summary>
    public SettingsPage()
    {
        InitializeComponent();
    }
}
