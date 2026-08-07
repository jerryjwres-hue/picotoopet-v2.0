using System.Diagnostics.CodeAnalysis;

// WPF ItemsSource 通过实例 DataContext 绑定该集合；不能为了 CA1822 改成 static。
[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF ItemsSource 需要 ProviderSessionViewModel 的实例属性绑定。",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ProviderSessionViewModel.UsageStatusOptions")]
