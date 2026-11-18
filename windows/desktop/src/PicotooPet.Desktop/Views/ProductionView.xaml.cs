using System.Windows.Controls;
using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>将候选卡的双击手势转发给本地播放命令。</summary>
public partial class ProductionView : UserControl
{
    public ProductionView() => InitializeComponent();

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
