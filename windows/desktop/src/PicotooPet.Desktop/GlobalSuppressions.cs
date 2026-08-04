using System.Diagnostics.CodeAnalysis;

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
