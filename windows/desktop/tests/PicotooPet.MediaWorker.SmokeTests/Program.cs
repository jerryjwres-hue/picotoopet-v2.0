using PicotooPet.Desktop.Services;

if (args.Length == 4 && args[0] == "--worker-key-probe")
{
    PicotooPet.MediaWorker.SmokeTests.WorkerSignerTests.Probe(args[1], args[2], bool.Parse(args[3]));
    return;
}
if (args.Contains("--worker-signing-vectors-only", StringComparer.Ordinal))
{
    PicotooPet.MediaWorker.SmokeTests.WorkerSignerTests.Vectors();
    return;
}
if (args.Length == 3 && args[0] == "--i2v-snapshot-crash-probe")
{
    await PicotooPet.MediaWorker.SmokeTests.DurableReferenceSnapshotTests.ProbeAsync(args[1],
        int.Parse(args[2], System.Globalization.CultureInfo.InvariantCulture));
    return;
}
if (args.Contains("--i2v-durable-only", StringComparer.Ordinal))
{
    await PicotooPet.MediaWorker.SmokeTests.DurableReferenceSnapshotTests.RunAsync();
    return;
}
if (args.Contains("--i2v-executor-only", StringComparer.Ordinal))
{
    await PicotooPet.MediaWorker.SmokeTests.I2VExecutorSnapshotTests.RunAsync();
    return;
}
if (args.Contains("--multishot-regression-only", StringComparer.Ordinal))
{
    await PicotooPet.MediaWorker.SmokeTests.MultiShotProductionTests.RunAsync();
    return;
}

if (args.Contains("--three-shot-gate-probe", StringComparer.Ordinal))
{
    PicotooPet.MediaWorker.SmokeTests.IndependentThreeShotGateTests.Probe(args);
    return;
}
if (args.Contains("--independent-three-shot-gate-only", StringComparer.Ordinal))
{
    await PicotooPet.MediaWorker.SmokeTests.IndependentThreeShotGateTests.RunAsync();
    return;
}

// ── Native Windows fake-API tests: execute the real shared library in the approved WPF build. ──
if (!typeof(ProductionExecutionService).GetConstructors().Any(ctor =>
        ctor.GetParameters().Any(parameter =>
            parameter.ParameterType.Name == "IProductionExecutionGateway")))
{
    throw new InvalidOperationException("P0_SHARED_EXECUTOR_GATEWAY_MISSING");
}
await PicotooPet.MediaWorker.SmokeTests.RecoveryTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.RecoveryFixTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.MultiShotProductionTests.RunAsync();
PicotooPet.MediaWorker.SmokeTests.ThreeShotAcceptanceGateTests.Run();
PicotooPet.MediaWorker.SmokeTests.ReferenceV11BindingTests.Run();
await PicotooPet.MediaWorker.SmokeTests.DurableReferenceSnapshotTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.I2VExecutorSnapshotTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.ShippingReferenceProofTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.WorkerSignerTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.WorkerExecutableIdentityTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.WorkerChallengePreflightTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.LegacyContractTests.RunAsync();
PicotooPet.MediaWorker.SmokeTests.SameExeHostTests.Run();
Console.WriteLine("P0_SAME_EXE_WORKER_JOURNAL_RECOVERY=PASS");
