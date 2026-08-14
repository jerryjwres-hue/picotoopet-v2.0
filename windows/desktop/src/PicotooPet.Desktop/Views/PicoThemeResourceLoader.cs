using System.Windows;

namespace PicotooPet.Desktop.Views;

/// <summary>为可独立实例化的 WPF 表面挂载产品主题，避免测试或设计器缺少 App 资源时崩溃。</summary>
internal static class PicoThemeResourceLoader
{
    private static readonly Uri ThemeUri = new(
        "pack://application:,,,/Picotoo%20Pet%20AI;component/Themes/PicotooTheme.xaml",
        UriKind.Absolute);                              // 显式定位桌面程序集，避免 smoke 测试把相对 URI 解析到测试程序集。

    /// <summary>只在控件本地尚未拥有主题时添加一次；不修改业务状态或全局设置。</summary>
    public static void Attach(FrameworkElement element)
    {
        ArgumentNullException.ThrowIfNull(element);

        if (element.Resources.Contains("PicoPageBackgroundBrush"))
        {
            return;
        }

        element.Resources.MergedDictionaries.Add(new ResourceDictionary
        {
            Source = ThemeUri,                           // 本地 BAML 主题，无网络、插件或外部文件依赖。
        });
    }
}
