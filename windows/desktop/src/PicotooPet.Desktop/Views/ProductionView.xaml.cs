using System.Windows.Controls;
using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>将候选卡的双击手势转发给本地播放命令。</summary>
public partial class ProductionView : UserControl
{
    public ProductionView() => InitializeComponent();

    private async void ChooseWorkerProject(object sender, System.Windows.RoutedEventArgs args)
    {
        if (DataContext is not ProductionViewModel model) return;
        // 使用系统文件夹选择器，用户无需输入路径、Ticket 或 SHA。
        var picker = new Microsoft.Win32.OpenFolderDialog
        {
            Title = "选择现有 Windows 视频项目根目录",
        };
        if (picker.ShowDialog(System.Windows.Window.GetWindow(this)) != true) return;
        try
        {
            await model.ChooseWorkerProjectAsync(picker.FolderName);
        }
        catch (System.Exception error)
        {
            System.Windows.MessageBox.Show(
                System.Windows.Window.GetWindow(this),
                error.Message,
                "视频项目目录",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning);
        }
    }

    private async void OpenBatch(object sender, System.Windows.RoutedEventArgs args)
    {
        if (DataContext is not ProductionViewModel model || !model.CanOpenBatch) return;
        var dialog = new LocalBatchDialog(model.HasConnection) { Owner = System.Windows.Window.GetWindow(this) };
        if (dialog.ShowDialog() == true && dialog.Selection is { } options)
            await model.ProcessBatchAsync(options);
    }

    private void PlayCandidate(object sender, MouseButtonEventArgs args)
    {
        if (sender is ListBox list && args.OriginalSource is System.Windows.DependencyObject source
            && ItemsControl.ContainerFromElement(list, source) is ListBoxItem
            && DataContext is ProductionViewModel model && model.PlayCommand.CanExecute(null))
        {
            model.PlayCommand.Execute(null);
        }
    }
}
