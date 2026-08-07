using System.Diagnostics.CodeAnalysis;

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF ItemsSource binding requires an instance property on ProviderSessionViewModel.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ProviderSessionViewModel.UsageStatusOptions")]
