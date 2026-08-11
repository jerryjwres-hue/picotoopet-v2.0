using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Creative Intelligence 真实 STA WPF RED/GREEN 布局合同。</summary>
internal static class CreativeIntelligenceWpfSmokeTests
{
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunOnStaThread();
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

    private static void RunOnStaThread()
    {
        var source = new CreativeEligibleSourceRecord(
            ResultPackageId: "11111111-1111-4111-8111-111111111111",
            WorkPackageId: "22222222-2222-4222-8222-222222222222",
            ProjectKey: "pet-dryer-us",
            AnalysisProfile: "reviews.voice_of_customer.v1",
            ResultDigest: new string('a', 64),
            Summary: "Drying time matters.",
            CreatedAt: DateTimeOffset.UtcNow);
        var viewModel = CreativeIntelligencePanelViewModel.CreateForSmokeTest(
            new[] { source },
            "creative.intelligence.v1 · healthy · mac-worker");
        viewModel.Sources[0].IsSelected = true;
        var panel = new CreativeIntelligencePanel { DataContext = viewModel };

        panel.Measure(new Size(1100, 700));
        panel.Arrange(new Rect(0, 0, 1100, 700));
        panel.UpdateLayout();

        SmokeAssert.True(panel.ActualWidth > 0 && panel.ActualHeight > 0, "Creative Intelligence panel did not layout");
        SmokeAssert.True(viewModel.CanPrepare, "一个合法同项目 PASS source 应允许准备创意方案");
        SmokeAssert.True(viewModel.CreativeBoundaryText.Contains("creative_ready != rendered != publish-ready", StringComparison.Ordinal), "必须明确 creative_ready 边界");
    }
}
