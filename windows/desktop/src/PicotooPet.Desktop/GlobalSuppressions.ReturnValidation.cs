using System.Diagnostics.CodeAnalysis;

[assembly: SuppressMessage(
    "Performance",
    "CA1822:Mark members as static",
    Justification = "WPF BindingPath requires an instance property on ReturnValidationViewModel.",
    Scope = "member",
    Target = "~P:PicotooPet.Desktop.ViewModels.ReturnValidationViewModel.SafetyNotice")]
