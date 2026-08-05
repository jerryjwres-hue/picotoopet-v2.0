using System.Diagnostics.CodeAnalysis;

// WPF 通过 ShellViewModel 的 DataContext 实例绑定版本文案，因此只对这两个属性精确保留实例语义。
[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds WindowTitle through the ShellViewModel DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ShellViewModel.WindowTitle")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds ControlCenterSubtitle through the ShellViewModel DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ShellViewModel.ControlCenterSubtitle")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.ContractVersion")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.ContractStatus")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.ProviderConfigured")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.ProviderStatus")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.CurrentDelivery")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.TrustChain")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.SecurityBoundaries")]

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF binds this read-only contract property through the page DataContext instance.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.CloudDevelopmentPageViewModel.PhaseMilestones")]
