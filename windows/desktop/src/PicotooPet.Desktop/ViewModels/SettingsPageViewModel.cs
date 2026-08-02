namespace PicotooPet.Desktop.ViewModels;

/// <summary>只承载非敏感 Mac 地址；设备令牌始终留在 PasswordBox 和 Credential Manager。</summary>
public sealed class SettingsPageViewModel : PageViewModel
{
    private string _macBaseUrl;

    /// <summary>使用当前已保存的 Mac Core 地址创建设置页。</summary>
    public SettingsPageViewModel(string macBaseUrl)
        : base("设置")
    {
        _macBaseUrl = macBaseUrl;
    }

    /// <summary>Mac Core HTTP/HTTPS 地址。</summary>
    public string MacBaseUrl
    {
        get => _macBaseUrl;
        set => SetProperty(ref _macBaseUrl, value);
    }
}
