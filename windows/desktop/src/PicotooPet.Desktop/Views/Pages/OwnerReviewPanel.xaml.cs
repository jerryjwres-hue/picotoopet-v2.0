using System.Windows;
using PicotooPet.Desktop.ViewModels;
using WpfUserControl = System.Windows.Controls.UserControl;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>
/// 主人结构化审核面板。独立控件：不接入现有 Goal Center 文件（由 #218/#221 持有），
/// 也不创建 Goal、不触发 Creative/Production/GPU。
/// </summary>
public partial class OwnerReviewPanel : WpfUserControl
{
    public OwnerReviewPanel()
    {
        InitializeComponent();
    }

    private OwnerReviewViewModel? ViewModel => DataContext as OwnerReviewViewModel;

    private void SaveCredentialButton_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is null) return;
        ViewModel.SaveCredential(CredentialBox.Password);
        CredentialBox.Clear();
    }

    private void ClearCredentialButton_Click(object sender, RoutedEventArgs e)
    {
        ViewModel?.ClearCredential();
        CredentialBox.Clear();
    }
}
