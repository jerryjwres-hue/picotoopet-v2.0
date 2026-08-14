using System.Windows;

namespace PicotooPet.Desktop.Views;

/// <summary>为可独立实例化的 WPF 表面挂载产品主题，避免测试或设计器缺少 App 资源时崩溃。</summary>
internal static class PicoThemeResourceLoader
{
    private static readonly Uri ThemeUri = new(
        "Themes/PicotooTheme.xaml",
        UriKind.Relative);                         // 相对应用资源根解析，保持安装包内离线可用。

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
            Source = ThemeUri,                     // 本地 BAML 主题，无网络、插件或外部文件依赖。
        });
    }
}
