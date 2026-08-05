using System.Diagnostics.CodeAnalysis;

// SafetyNotice 必须保持实例属性，供 WPF BindingPath 读取；只抑制这一成员。
[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF BindingPath requires an instance property on ReturnValidationViewModel.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ReturnValidationViewModel.SafetyNotice")]
