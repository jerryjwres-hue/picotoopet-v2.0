using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Goal Center 保留交接动作并只在 ready 时显示粘贴入口。</summary>
internal static class GoalVideoReturnPanelWpfSmokeTests
{
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                var panel = new GoalCenterPanel();
                panel.Measure(new Size(1100, 500));
                panel.Arrange(new Rect(0, 0, 1100, 500));
                panel.UpdateLayout();

                SmokeAssert.True(panel.FindName("CopyPromptButton") is Button, "复制 GPT 提示词按钮丢失");
                SmokeAssert.True(panel.FindName("SaveHandoffButton") is Button, "保存交接 ZIP 按钮丢失");
                var paste = panel.FindName("PasteGoalVideoReturnButton") as Button
                    ?? throw new InvalidOperationException("缺少粘贴 GPT 返回按钮");
                var openFinal = panel.FindName("OpenFinalVideoButton") as Button
                    ?? throw new InvalidOperationException("缺少打开最终视频按钮");
                SmokeAssert.Equal(Visibility.Collapsed, paste.Visibility, "未就绪交接错误显示粘贴入口");
                SmokeAssert.Equal(Visibility.Collapsed, openFinal.Visibility, "未验证成品错误显示打开入口");

                var continuation = new GoalVideoContinuationViewModel(new NoopGateway());
                continuation.SetContext(Goal(), Handoff());
                panel.DataContext = new { VideoContinuation = continuation };
                panel.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
                panel.UpdateLayout();
                SmokeAssert.Equal(Visibility.Visible, paste.Visibility, "就绪交接未显示粘贴入口");
                SmokeAssert.Equal(Visibility.Collapsed, openFinal.Visibility, "没有最终成品时错误显示打开入口");
                SmokeAssert.True(CountVisual<PasswordBox>(panel) == 0, "Goal Center 不得收集凭据");
                SmokeAssert.True(CountVisual<System.Windows.Controls.WebBrowser>(panel) == 0, "Goal Center 不得嵌入 Web GPT");
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static int CountVisual<T>(DependencyObject root) where T : DependencyObject
    {
        var count = root is T ? 1 : 0;
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            count += CountVisual<T>(VisualTreeHelper.GetChild(root, index));
        }
        return count;
    }

    private static HumanGoalRecord Goal() => new(
        "goal-1", null, "workflow-1", "human", "product.research_to_video", "P1",
        "研究产品并生成视频", JsonDocument.Parse("{}").RootElement.Clone(), "local-first",
        false, null, "Completed", "goal-key", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);

    private static GoalHandoffMetadataRecord Handoff() => new(
        "1.0", "goal-1", true, "goal-1.zip", new string('a', 64), 100,
        "web-gpt-master-v1.0", true);

    private sealed class NoopGateway : IGoalVideoContinuationGateway
    {
        public Task<GoalVideoContinuationRecord> SubmitGoalVideoReturnAsync(
            string goalId,
            JsonElement payload,
            CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<GoalVideoContinuationRecord> GetGoalVideoContinuationAsync(
            string goalId,
            CancellationToken cancellationToken) => throw new NotSupportedException();
    }
}
