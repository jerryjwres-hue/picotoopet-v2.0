using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>只将既有 ProductionPanel 暴露到真正启动的高级 Shell，不增加第二套生产执行器。</summary>
public partial class ShellWindow
{
    private Window? _productionPanelWindow;

    /// <summary>用户明确点击才打开固定生产面板；打开窗口本身不会授权渲染或发送 GPU POST。</summary>
    private void OpenProductionPanel_Click(object sender, RoutedEventArgs e)
    {
        if (_productionPanelWindow is { IsVisible: true } existing)
        {
            existing.Activate();
            return;
        }

        ProductionPanelViewModel? model = null;
        try
        {
            // 唯一 Session   : 直接复用现有 Mac Core 配对和持久化生产状态。
            // 唯一执行器     : ProductionPanelViewModel 继续使用现有 ProductionExecutionService。
            // 人工授权边界   : 这里只创建 UI，不调用 StartAsync、PreflightAsync 或 VisualReview。
            model = new ProductionPanelViewModel(_session);
            var panel = new ProductionPanel { DataContext = model };
            var window = new Window
            {
                Title                 = "PicotooPet · 本地生产与只读视觉审片",
                Owner                 = this,
                Width                 = 1120,
                Height                = 800,
                MinWidth              = 940,
                MinHeight             = 650,
                WindowStartupLocation = WindowStartupLocation.CenterOwner,
                Content               = panel,
            };

            var ownedModel = model;
            window.Closed += (_, _) =>
            {
                ownedModel.Dispose();
                if (ReferenceEquals(_productionPanelWindow, window))
                {
                    _productionPanelWindow = null;
                }
            };

            _productionPanelWindow = window;
            window.Show();
        }
        catch (Exception exception)
        {
            model?.Dispose();
            _productionPanelWindow = null;
            _logger.Error("本地生产与视觉审片面板无法打开。", exception);
            MessageBox.Show(
                this,
                "本地生产面板未打开；没有启动渲染，也没有批准 GPU。请检查应用日志。",
                "本地生产面板不可用",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }
}
