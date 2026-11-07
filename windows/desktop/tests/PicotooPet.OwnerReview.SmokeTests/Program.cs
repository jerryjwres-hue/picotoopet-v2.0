using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows.Controls;
using PicotooPet.Desktop.Core.OwnerReview;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.OwnerReview.SmokeTests;

/// <summary>Owner Structured Review（#232）：仅合成数据 + Mock HTTP，不触网、不触 Core/GPU。</summary>
internal static class Program
{
    private const string Cred = "synthetic-owner-review-credential-0001";
    private static readonly JsonSerializerOptions Web = new(JsonSerializerDefaults.Web);
    private static int _passed;

    [STAThread]
    private static async Task<int> Main()
    {
        var failures = new List<string>();
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("openapi_digest_and_wire_shape", OpenApiShapeAsync),
            ("transport_blocks_lan_and_unverified_encryption", TransportBlockedAsync),
            ("dpapi_store_is_dedicated_and_encrypted", DpapiStoreAsync),
            ("client_sends_only_owner_credential_to_owner_paths", ClientAuthAsync),
            ("http_negative_401_403_409_422", HttpNegativeAsync),
            ("missing_credential_never_calls_http", MissingCredentialAsync),
            ("no_default_confirm_and_unknown_blocks", DraftRulesAsync),
            ("unknown_and_empty_list_corrections_have_canonical_types", UnknownListTypesAsync),
            ("static_story_requires_separate_owner_opt_in", StaticOptInAsync),
            ("preview_writes_nothing_and_commit_is_explicit", FlowAsync),
            ("idempotent_replay_uses_same_key_and_body", ReplayAsync),
            ("stale_409_forces_reload_never_overwrites", StaleAsync),
            ("cancel_and_restart_resume_are_side_effect_free", CancelResumeAsync),
            ("wpf_panel_binds_and_separates_identity_from_intent", () => OnSta(WpfPanel)),
        };
        foreach (var (name, run) in tests)
        {
            try
            {
                await run().ConfigureAwait(false);
                _passed++;
                Console.WriteLine("PASS " + name);
            }
            catch (Exception error)
            {
                failures.Add(name);
                Console.Error.WriteLine("FAIL " + name + ": " + error);
            }
        }
        Console.WriteLine(failures.Count == 0
            ? $"OWNER_REVIEW_UI_SMOKE=PASS tests={_passed}; REAL_HTTP=0; GPU_POST=0; TRANSPORT_SECURITY=BLOCKED"
            : "OWNER_REVIEW_UI_SMOKE=FAIL " + string.Join(",", failures));
        return failures.Count == 0 ? 0 : 1;
    }

    // ---- helpers -------------------------------------------------------------------------

    private static void True(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void Eq<T>(T expected, T actual, string message)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new InvalidOperationException($"{message}; expected={expected} actual={actual}");
    }

    private static (OwnerReviewClient Client, MockOwnerReviewCore Core, InMemoryOwnerReviewCredentialStore Store) NewClient(bool withCredential = true)
    {
        var core = new MockOwnerReviewCore();
        var store = new InMemoryOwnerReviewCredentialStore();
        if (withCredential) store.Save(Cred);
        return (new OwnerReviewClient(MockOwnerReviewCore.Base, OwnerReviewTransportMode.Mock, store, core), core, store);
    }

    private static async Task Settle(OwnerReviewViewModel vm)
    {
        var idle = 0;
        for (var i = 0; i < 400 && idle < 3; i++)
        {
            await Task.Delay(15).ConfigureAwait(false);
            idle = vm.Busy ? 0 : idle + 1;
        }
    }

    private static async Task Run(OwnerReviewViewModel vm, AsyncRelayCommand command)
    {
        command.Execute(null);
        await Settle(vm).ConfigureAwait(false);
    }

    /// <summary>完成全部字段的合法决定：CONFIRM 可确认者，其余 CORRECT。</summary>
    private static void DecideAllReady(OwnerReviewViewModel vm)
    {
        foreach (var row in vm.IdentityFields.Concat(vm.IntentFields))
        {
            if (row.CanConfirm) row.IsConfirm = true;
            else { row.IsCorrect = true; row.CorrectedText = "owner-corrected"; }
        }
    }

    private static string FindRepoFile(string relative)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, relative);
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        throw new FileNotFoundException(relative);
    }

    // ---- tests ---------------------------------------------------------------------------

    private static Task OpenApiShapeAsync()
    {
        var path = FindRepoFile(Path.Combine("contracts", "openapi", "mac_core_v1.openapi.json"));
        // Windows checkout 可能把 LF 转成 CRLF（core.autocrlf）；摘要按冻结的 LF 字节计算。
        var bytes = File.ReadAllBytes(path).Where(b => b != 0x0D).ToArray();
        // The review contract is pinned to PR #235's latest approved source bytes.
        // A future drift must trigger explicit re-review, never a silent informational PASS.
        var digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        Eq(OwnerReviewWire.FrozenOpenApiSha256, digest, "Core OpenAPI digest must be explicitly reapproved");
        var api = JsonNode.Parse(bytes)!;
        var paths = api["paths"]!.AsObject();
        True(paths.ContainsKey("/api/v1/owner-structured-reviews/goals/{goal_id}/proposal"), "proposal path");
        True(paths.ContainsKey("/api/v1/owner-structured-reviews/preview"), "preview path");
        True(paths.ContainsKey("/api/v1/owner-structured-reviews/commit"), "commit path");
        var schemas = api["components"]!["schemas"]!.AsObject();
        foreach (var name in new[] { "OwnerStructuredReviewPreviewRequest", "OwnerStructuredReviewPreview", "OwnerStructuredReviewCommit" })
        {
            var schema = schemas[name]!;
            True(schema["properties"]!.AsObject().ContainsKey("story_policy_opt_in"), name + ": explicit opt-in field missing");
            True(!schema["required"]!.AsArray().Any(x => x!.GetValue<string>() == "story_policy_opt_in"),
                name + ": opt-in must remain optional/default-off");
            True(schema["properties"]!["story_policy_opt_in"]!.ToJsonString().Contains(
                OwnerReviewWire.StaticPetStoryPolicy, StringComparison.Ordinal),
                name + ": opt-in policy identifier mismatch");
        }

        void Subset(object sample, string schema)
        {
            var wire = JsonNode.Parse(JsonSerializer.Serialize(sample, sample.GetType(), Web))!.AsObject();
            var allowed = schemas[schema]!["properties"]!.AsObject().Select(p => p.Key).ToHashSet();
            foreach (var key in wire.Select(p => p.Key))
                True(allowed.Contains(key), $"{schema}: unexpected wire property {key}");
            foreach (var required in schemas[schema]!["required"]!.AsArray().Select(r => r!.GetValue<string>()))
                True(wire.ContainsKey(required), $"{schema}: missing required {required}");
        }

        var preview = new OwnerReviewPreviewRequest("g", "a", Digest64('a'), [new OwnerFieldDecision("f", "CONFIRM")]);
        Subset(preview, "OwnerStructuredReviewPreviewRequest");
        Subset(new OwnerFieldDecision("f", "CORRECT", MockOwnerReviewCore.ParseElement("\"x\"")), "OwnerStructuredFieldDecision");
        Subset(new OwnerReviewCommitRequest(preview, Digest64('b'), Digest64('c'), Digest64('d')), "OwnerStructuredReviewCommitRequest");

        // 响应：合成响应必须能被客户端 DTO 完整解析（DTO 不得丢失 required 字段）。
        foreach (var (schema, sample) in new[]
        {
            ("OwnerStructuredReviewProposal", MockOwnerReviewCore.Proposal()),
            ("OwnerStructuredReviewPreview", MockOwnerReviewCore.Preview(false)),
            ("OwnerStructuredReviewCommit", MockOwnerReviewCore.Commit()),
        })
        {
            foreach (var required in schemas[schema]!["required"]!.AsArray().Select(r => r!.GetValue<string>()))
                True(sample.ContainsKey(required), $"mock {schema} missing {required}");
        }
        return Task.CompletedTask;
    }

    private static string Digest64(char c) => new(c, 64);

    private static Task TransportBlockedAsync()
    {
        var store = new InMemoryOwnerReviewCredentialStore();
        foreach (var uri in new[]
        {
            "http://192.168.68.70:8766/", "https://192.168.68.70:8766/", "http://core.example.com/",
            "https://owner-review-mock.invalid/",
        })
        {
            ExpectBlocked(() => Make(new Uri(uri), OwnerReviewTransportMode.LoopbackOnly, store), uri + " loopback-only");
        }
        // 经验收的加密传输尚未交付：任何地址都被硬阻断。
        ExpectBlocked(() => Make(new Uri("https://mac-core.local/"), OwnerReviewTransportMode.VerifiedEncrypted, store), "verified-encrypted");
        // Mock 只允许保留域名 .invalid，且必须注入 handler。
        ExpectBlocked(() => Make(new Uri("https://192.168.68.70/"), OwnerReviewTransportMode.Mock, store, new MockOwnerReviewCore()), "mock real host");
        True(Throws<ArgumentException>(() => Make(MockOwnerReviewCore.Base, OwnerReviewTransportMode.Mock, store)), "mock needs handler");
        True(Throws<ArgumentException>(() => Make(new Uri("http://127.0.0.1:9/"), OwnerReviewTransportMode.LoopbackOnly, store, new MockOwnerReviewCore())), "handler only in mock");
        // 本机回环允许构造（不发请求）。
        new OwnerReviewClient(new Uri("http://127.0.0.1:8766/"), OwnerReviewTransportMode.LoopbackOnly, store).Dispose();
        True(!OwnerReviewTransportGate.EncryptedMacTransportAccepted, "encrypted Mac transport must remain unaccepted");
        return Task.CompletedTask;
    }

    private static OwnerReviewClient Make(Uri uri, OwnerReviewTransportMode mode, IOwnerReviewCredentialStore store, HttpMessageHandler? handler = null) =>
        new(uri, mode, store, handler);

    private static void ExpectBlocked(Func<OwnerReviewClient> make, string label)
    {
        try { make().Dispose(); }
        catch (OwnerReviewException e) when (e.Kind == OwnerReviewFailureKind.TransportBlocked) { return; }
        throw new InvalidOperationException("transport not blocked: " + label);
    }

    private static bool Throws<T>(Action action) where T : Exception
    {
        try { action(); }
        catch (T) { return true; }
        return false;
    }

    private static Task DpapiStoreAsync()
    {
        var directory = Path.Combine(Path.GetTempPath(), "owner-review-smoke-" + Guid.NewGuid().ToString("N"));
        var path = Path.Combine(directory, "owner.cred.dpapi");
        try
        {
            var store = new DpapiOwnerReviewCredentialStore(path);
            True(store.Read() is null, "empty store");
            store.Save(Cred);
            var raw = File.ReadAllBytes(path);
            True(raw.Length > 0 && !System.Text.Encoding.UTF8.GetString(raw).Contains(Cred, StringComparison.Ordinal), "ciphertext must not contain plaintext");
            Eq(Cred, store.Read(), "round trip");
            // 专用：与设备令牌的 Credential Manager 目标完全无关，且不会读到设备令牌。
            var device = new CredentialManagerTokenStore("PicotooPetV2/OwnerReviewSmokeIsolated-" + Guid.NewGuid().ToString("N"));
            True(device.Read() is null, "device token store must stay untouched/empty");
            True(Throws<ArgumentException>(() => store.Save("has space")), "rejects whitespace credential");
            True(Throws<ArgumentException>(() => store.Save(new string('x', 600))), "rejects oversized credential");
            store.Delete();
            True(store.Read() is null && !File.Exists(path), "delete");
            // 篡改密文 → 解密失败，不得返回垃圾明文。
            store.Save(Cred);
            var tampered = File.ReadAllBytes(path);
            tampered[^1] ^= 0xFF;
            File.WriteAllBytes(path, tampered);
            True(Throws<CryptographicException>(() => store.Read()), "tampered ciphertext must fail closed");
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
        return Task.CompletedTask;
    }

    private static async Task ClientAuthAsync()
    {
        var (client, core, _) = NewClient();
        using (client)
        {
            var proposal = await client.GetProposalAsync(MockOwnerReviewCore.Goal, CancellationToken.None).ConfigureAwait(false);
            Eq(MockOwnerReviewCore.Digest, proposal.ProposalDigest, "proposal digest");
            var draft = new OwnerReviewDraft(proposal);
            foreach (var f in draft.Fields) draft.SetDecision(f.Proposal.FieldPath, f.CanConfirm ? "CONFIRM" : "UNKNOWN");
            await client.PreviewAsync(draft.BuildPreviewRequest(), CancellationToken.None).ConfigureAwait(false);
        }
        True(core.Requests.Count == 2, "two requests");
        foreach (var request in core.Requests)
        {
            True(request.Path.StartsWith("/api/v1/owner-structured-reviews/", StringComparison.Ordinal), "only owner-review paths: " + request.Path);
            Eq("Bearer " + Cred, request.Authorization, "owner credential bearer");
            True(!request.Path.Contains("goals/creative", StringComparison.Ordinal), "no Goal creation path");
        }
        True(core.CountPath("/commit") == 0, "preview must not commit");
        await ExpectAsync<ArgumentException>(() => new OwnerReviewClient(MockOwnerReviewCore.Base, OwnerReviewTransportMode.Mock, new InMemoryOwnerReviewCredentialStore(), core)
            .GetProposalAsync("../../goals", CancellationToken.None)).ConfigureAwait(false);
    }

    private static async Task ExpectAsync<T>(Func<Task> action) where T : Exception
    {
        try { await action().ConfigureAwait(false); }
        catch (T) { return; }
        throw new InvalidOperationException("expected " + typeof(T).Name);
    }

    private static async Task HttpNegativeAsync()
    {
        foreach (var (status, code, kind) in new[]
        {
            (401, "OWNER_AUTH_INVALID", OwnerReviewFailureKind.Unauthorized),
            (403, "OWNER_REVIEW_ENCRYPTED_TRANSPORT_REQUIRED", OwnerReviewFailureKind.Forbidden),
            (403, "OWNER_SCOPE_DENIED", OwnerReviewFailureKind.Forbidden),
            (409, "OWNER_REVIEW_PROPOSAL_STALE", OwnerReviewFailureKind.Conflict),
            (409, "OWNER_REVIEW_PREVIEW_MISMATCH", OwnerReviewFailureKind.Conflict),
            (409, "OWNER_REVIEW_IDEMPOTENCY_CONFLICT", OwnerReviewFailureKind.Conflict),
            (422, "VALIDATION_ERROR", OwnerReviewFailureKind.Validation),
            (500, "INTERNAL", OwnerReviewFailureKind.Unavailable),
        })
        {
            var (client, core, _) = NewClient();
            core.Override = _ => (status, MockOwnerReviewCore.Error(code));
            using (client)
            {
                var error = await Catch(() => client.GetProposalAsync(MockOwnerReviewCore.Goal, CancellationToken.None)).ConfigureAwait(false);
                Eq(kind, error.Kind, $"{status} kind");
                Eq(status, error.StatusCode, $"{status} status");
                Eq(code, error.Code, $"{status} code");
                True(!error.Message.Contains(Cred, StringComparison.Ordinal) && !error.ChineseMessage.Contains(Cred, StringComparison.Ordinal), "no secret in error");
                True(error.ChineseMessage.Length > 4, "chinese message");
                Eq(status == 409, error.RequiresReload, "409 requires reload");
            }
        }
        // 422：FastAPI 校验体不带 error 封装时仍然可分类；畸形/超大响应体不被回显。
        var (c2, core2, _) = NewClient();
        core2.Override = _ => (422, "{\"detail\":[{\"loc\":[\"body\"],\"msg\":\"bad\"}]}");
        using (c2)
        {
            var e = await Catch(() => c2.PreviewAsync(new OwnerReviewPreviewRequest("g", "a", Digest64('a'), []), CancellationToken.None)).ConfigureAwait(false);
            Eq(OwnerReviewFailureKind.Validation, e.Kind, "422 detail body");
            Eq("OWNER_REVIEW_HTTP_422", e.Code, "422 fallback code");
        }
        var (c3, core3, _) = NewClient();
        core3.Override = _ => (200, "{not json");
        using (c3)
        {
            var e = await Catch(() => c3.GetProposalAsync(MockOwnerReviewCore.Goal, CancellationToken.None)).ConfigureAwait(false);
            Eq("OWNER_REVIEW_RESPONSE_INVALID", e.Code, "malformed 200");
        }
        var (c4, core4, _) = NewClient();
        core4.Override = _ => (200, new string('x', 1_100_000));
        using (c4)
        {
            var e = await Catch(() => c4.GetProposalAsync(MockOwnerReviewCore.Goal, CancellationToken.None)).ConfigureAwait(false);
            Eq("OWNER_REVIEW_RESPONSE_TOO_LARGE", e.Code, "oversized");
        }
    }

    private static async Task<OwnerReviewException> Catch(Func<Task> action)
    {
        try { await action().ConfigureAwait(false); }
        catch (OwnerReviewException e) { return e; }
        throw new InvalidOperationException("expected OwnerReviewException");
    }

    private static async Task MissingCredentialAsync()
    {
        var (client, core, _) = NewClient(withCredential: false);
        using (client)
        {
            var e = await Catch(() => client.GetProposalAsync(MockOwnerReviewCore.Goal, CancellationToken.None)).ConfigureAwait(false);
            Eq(OwnerReviewFailureKind.CredentialMissing, e.Kind, "credential missing");
        }
        Eq(0, core.Requests.Count, "no HTTP without owner credential");
    }

    private static Task DraftRulesAsync()
    {
        var proposal = JsonSerializer.Deserialize<OwnerReviewProposal>(MockOwnerReviewCore.Proposal().ToJsonString(), Web)!;
        var draft = new OwnerReviewDraft(proposal);
        True(draft.FirstValidationProblem() is not null, "undecided fields block preview (no default confirm)");
        True(Throws<InvalidOperationException>(() => draft.BuildPreviewRequest()), "cannot build request while undecided");
        // 身份事实 与 创作意图 分组。
        var intentPaths = draft.Group(OwnerReviewFieldGroup.CreativeIntent)
            .Select(f => f.Proposal.FieldPath).ToHashSet(StringComparer.Ordinal);
        True(intentPaths.Count == 3
                && intentPaths.Contains("allowed_events")
                && intentPaths.Contains("pose_lock.head_direction")
                && intentPaths.Contains("scene_lock.lighting"),
            "pose/scene and events are creative intent even when Core source is UNKNOWN");
        True(!draft.Group(OwnerReviewFieldGroup.IdentityAndSceneFacts).Any(f => f.Proposal.FieldPath == "allowed_events"), "identity group excludes intent");
        // UNKNOWN / CONFLICT 来源不可直接 CONFIRM。
        foreach (var f in draft.Fields) draft.SetDecision(f.Proposal.FieldPath, "UNKNOWN");
        True(draft.FirstValidationProblem() is null, "all-UNKNOWN is a decided (NEEDS_HUMAN) state");
        draft.SetDecision("pose_lock.head_direction", "CONFIRM");
        True(draft.FirstValidationProblem()!.Contains("pose_lock.head_direction", StringComparison.Ordinal), "UNKNOWN source cannot be confirmed");
        draft.SetDecision("scene_lock.lighting", "CONFIRM");
        True(draft.FirstValidationProblem()!.Contains("lighting", StringComparison.Ordinal) || draft.FirstValidationProblem()!.Contains("head_direction", StringComparison.Ordinal), "CONFLICT source cannot be confirmed either");
        // CORRECT 必须有更正值。
        draft.SetDecision("pose_lock.head_direction", "CORRECT");
        True(draft.FirstValidationProblem()!.Contains("更正值", StringComparison.Ordinal), "correct needs value");
        draft.SetDecision("pose_lock.head_direction", "CORRECT", "toward camera");
        draft.SetDecision("scene_lock.lighting", "UNKNOWN");
        draft.SetDecision("subject_lock.species", "CONFIRM");
        draft.SetDecision("subject_lock.distinguishing_marks", "CORRECT", "mark-a；mark-b\nmark-c");
        draft.SetDecision("allowed_events", "CONFIRM");
        True(draft.FirstValidationProblem() is null, "fully decided");
        var request = draft.BuildPreviewRequest();
        var marks = request.Decisions.Single(d => d.FieldPath == "subject_lock.distinguishing_marks").CorrectedValue!.Value;
        Eq(JsonValueKind.Array, marks.ValueKind, "list correction sent as array");
        Eq(3, marks.GetArrayLength(), "three marks");
        True(request.Decisions.Single(d => d.FieldPath == "subject_lock.species").CorrectedValue is null, "confirm carries no correction");
        Eq(MockOwnerReviewCore.Digest, request.ProposalDigest, "proposal digest comes from Core");
        // UNKNOWN 决定 → NEEDS_HUMAN → 不可提交。
        draft.AcceptPreview(JsonSerializer.Deserialize<OwnerReviewPreview>(MockOwnerReviewCore.Preview(needsHuman: true).ToJsonString(), Web)!);
        Eq(OwnerReviewCommitBlock.NeedsHuman, draft.CommitBlock(), "NEEDS_HUMAN blocks commit");
        return Task.CompletedTask;
    }

    private static Task UnknownListTypesAsync()
    {
        var proposal = JsonSerializer.Deserialize<OwnerReviewProposal>(
            MockOwnerReviewCore.Proposal().ToJsonString(), Web)!;
        var fields = proposal.Fields.ToDictionary(pair => pair.Key, pair => pair.Value);
        foreach (var path in new[]
        {
            "subject_lock.distinguishing_marks",
            "scene_lock.temporary_accessories",
            "camera_lock.allowed_framings",
            "allowed_events",
        })
        {
            fields[path] = new OwnerFieldProposal(path, OwnerReviewWire.StatusUnknown);
        }
        var draft = new OwnerReviewDraft(proposal with { Fields = fields });
        foreach (var field in draft.Fields)
        {
            var path = field.Proposal.FieldPath;
            if (path == "subject_lock.distinguishing_marks" || path == "scene_lock.temporary_accessories")
                draft.SetDecision(path, OwnerReviewWire.DecisionCorrect, "");
            else if (path == "camera_lock.allowed_framings")
                draft.SetDecision(path, OwnerReviewWire.DecisionCorrect, "locked medium shot；locked close-up");
            else if (path == "allowed_events")
                draft.SetDecision(path, OwnerReviewWire.DecisionCorrect, "BLINK_AND_REOPEN；SUBTLE_BREATHING");
            else
                draft.SetDecision(path, field.CanConfirm ? OwnerReviewWire.DecisionConfirm : OwnerReviewWire.DecisionUnknown);
        }
        True(draft.FirstValidationProblem() is null, "optional empty arrays are a deliberate correction");
        var decisions = draft.BuildPreviewRequest().Decisions;
        foreach (var path in new[]
        {
            "subject_lock.distinguishing_marks", "scene_lock.temporary_accessories",
            "camera_lock.allowed_framings", "allowed_events",
        })
        {
            var value = decisions.Single(x => x.FieldPath == path).CorrectedValue!.Value;
            Eq(JsonValueKind.Array, value.ValueKind, path + " UNKNOWN correction must be a JSON array");
            Eq(path is "subject_lock.distinguishing_marks" or "scene_lock.temporary_accessories" ? 0 : 2,
               value.GetArrayLength(), path + " must preserve empty/nonempty list cardinality");
        }
        return Task.CompletedTask;
    }

    private static async Task StaticOptInAsync()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            DecideAllReady(vm);
            True(!vm.StaticPetStorySelected, "no implicit policy selection");
            vm.StaticPetStorySelected = true;
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            var requested = core.Requests.Last(x => x.Path.EndsWith("/preview", StringComparison.Ordinal));
            Eq(OwnerReviewWire.StaticPetStoryPolicy,
               JsonNode.Parse(requested.Body)!["story_policy_opt_in"]!.GetValue<string>(),
               "explicit policy must be sent to Core Preview");
            True(vm.PreviewSummary.Contains(OwnerReviewWire.StaticPetStoryPolicy, StringComparison.Ordinal),
                "only a Core-echoed policy is displayed");
            vm.OwnerConfirmed = true;
            vm.StaticPetStorySelected = false;
            True(!vm.OwnerConfirmed && !vm.CommitCommand.CanExecute(null),
                "changing policy revokes prior preview and owner consent");
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            vm.OwnerConfirmed = true;
            await Run(vm, vm.CommitCommand).ConfigureAwait(false);
            var committed = core.Requests.Last(x => x.Path.EndsWith("/commit", StringComparison.Ordinal));
            True(JsonNode.Parse(committed.Body)!["preview_request"]!["story_policy_opt_in"] is null,
                "an unselected policy must NOT be stored in the frozen commit");
        }
    }

    private static async Task FlowAsync()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            Eq("主人审核凭据：已保存（专用 DPAPI 存储，不显示明文）", vm.CredentialStatus, "credential status");
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            True(vm.HasProposal, "proposal loaded");
            Eq(4, vm.IdentityFields.Count, "identity rows");
            Eq(1, vm.IntentFields.Count, "one intent row");
            // 空决定：预览被拒绝，Core 未被调用。
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            True(vm.ErrorText.Contains("尚未决定", StringComparison.Ordinal), "undecided message");
            Eq(0, core.CountPath("/preview"), "no preview call while undecided");
            DecideAllReady(vm);
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            Eq(1, core.CountPath("/preview"), "preview called once");
            Eq(0, core.CountPath("/commit"), "preview wrote nothing");
            True(vm.PreviewSummary.Contains("READY", StringComparison.Ordinal) && vm.PreviewSummary.Contains(new string('7', 64), StringComparison.Ordinal), "preview shows Core digests");
            // 未勾选显式确认：提交命令不可执行，即使强行执行也不会发请求。
            True(!vm.CommitCommand.CanExecute(null), "commit disabled before explicit confirmation");
            vm.CommitCommand.Execute(null);
            await Settle(vm).ConfigureAwait(false);
            Eq(0, core.CountPath("/commit"), "no commit without explicit confirmation");
            vm.OwnerConfirmed = true;
            True(vm.CommitCommand.CanExecute(null), "commit enabled after explicit confirmation");
            await Run(vm, vm.CommitCommand).ConfigureAwait(false);
            Eq(1, core.CountPath("/commit"), "one commit");
            var commit = core.Requests.Single(r => r.Path.EndsWith("/commit", StringComparison.Ordinal));
            True(commit.IdempotencyKey is { Length: > 8 } key && key.StartsWith("owner-review-", StringComparison.Ordinal), "Idempotency-Key header present");
            True(vm.CommitSummary.Contains("commit-synthetic-1", StringComparison.Ordinal), "commit summary");
            // 全部请求都只落在主人审核路径；没有 Goal/Creative/Comfy 工作。
            True(core.Requests.All(r => r.Path.StartsWith("/api/v1/owner-structured-reviews/", StringComparison.Ordinal)), "no other endpoint touched");
            var body = JsonNode.Parse(commit.Body)!;
            Eq(new string('7', 64), body["preview_digest"]!.GetValue<string>(), "commit echoes Core preview digest");
            Eq(new string('6', 64), body["review_digest"]!.GetValue<string>(), "commit echoes Core review digest");
        }
    }

    private static async Task ReplayAsync()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            DecideAllReady(vm);
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            vm.OwnerConfirmed = true;
            // 第一次提交遭遇瞬时 503；同一预览的重试必须使用同一个键和同一个正文。
            var calls = 0;
            core.Override = r =>
            {
                if (!r.Path.EndsWith("/commit", StringComparison.Ordinal)) return null;
                return ++calls == 1 ? (503, MockOwnerReviewCore.Error("UNAVAILABLE")) : null;
            };
            await Run(vm, vm.CommitCommand).ConfigureAwait(false);
            True(vm.ErrorText.Length > 0, "transient failure surfaced");
            vm.OwnerConfirmed = true;
            await Run(vm, vm.CommitCommand).ConfigureAwait(false);
            var commits = core.Requests.Where(r => r.Path.EndsWith("/commit", StringComparison.Ordinal)).ToList();
            Eq(2, commits.Count, "two attempts");
            Eq(commits[0].IdempotencyKey, commits[1].IdempotencyKey, "same Idempotency-Key on exact replay");
            Eq(commits[0].Body, commits[1].Body, "same body on exact replay");
        }
    }

    private static async Task StaleAsync()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            DecideAllReady(vm);
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            vm.OwnerConfirmed = true;
            core.Override = r => r.Path.EndsWith("/commit", StringComparison.Ordinal)
                ? (409, MockOwnerReviewCore.Error("OWNER_REVIEW_SOURCE_STALE")) : null;
            await Run(vm, vm.CommitCommand).ConfigureAwait(false);
            True(vm.ErrorText.Contains("重新加载", StringComparison.Ordinal), "409 asks for safe reload");
            True(!vm.OwnerConfirmed && vm.PreviewSummary.Length == 0, "409 clears explicit confirmation and preview");
            True(vm.Draft is null && !vm.HasProposal, "409 destroys the actual draft");
            True(!vm.CommitCommand.CanExecute(null), "old commit must remain impossible even if re-checked");
            vm.OwnerConfirmed = true;
            True(!vm.CommitCommand.CanExecute(null), "re-checked consent cannot resurrect stale preview");
            Eq(1, core.CountPath("/commit"), "no automatic force/retry after 409");
            // A NEW Core proposal is mandatory before a fresh Preview and Idempotency-Key.
            core.Override = null;
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            DecideAllReady(vm);
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            var keyBefore = vm.IdempotencyKey;
            vm.OwnerConfirmed = true;
            var row = vm.IdentityFields.First(f => f.CanConfirm);
            row.IsUnknown = true;
            True(!vm.OwnerConfirmed, "changing a decision clears explicit confirmation");
            True(vm.Draft!.CommitBlock() is OwnerReviewCommitBlock.NoPreview or OwnerReviewCommitBlock.PreviewStale,
                "preview invalidated by change");
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            True(vm.IdempotencyKey != keyBefore, "new preview gets a new Idempotency-Key");
        }
    }

    private static async Task CancelResumeAsync()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            await Run(vm, vm.LoadProposalCommand).ConfigureAwait(false);
            DecideAllReady(vm);
            await Run(vm, vm.PreviewCommand).ConfigureAwait(false);
            vm.OwnerConfirmed = true;
            var before = core.Requests.Count;
            await Run(vm, vm.CancelCommand).ConfigureAwait(false);
            Eq(before, core.Requests.Count, "cancel sends nothing");
            True(!vm.HasProposal && vm.IdentityFields.Count == 0 && !vm.OwnerConfirmed, "cancel discards draft");
            // 重启恢复：新的视图模型从 Core 重新读取提案，不继承任何旧确认。
            var restarted = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            await Run(restarted, restarted.LoadProposalCommand).ConfigureAwait(false);
            True(restarted.HasProposal && !restarted.OwnerConfirmed && restarted.IdempotencyKey is null, "resume starts fresh from Core");
            True(restarted.IdentityFields.All(f => f.Decision is null), "no inherited decisions");
            Eq(0, core.CountPath("/commit"), "no commit ever happened");
            // 凭据清除后无法再请求。
            restarted.ClearCredential();
            await Run(restarted, restarted.LoadProposalCommand).ConfigureAwait(false);
            True(restarted.ErrorText.Contains("凭据", StringComparison.Ordinal), "credential cleared message");
        }
    }

    private static Task OnSta(Action action)
    {
        var done = new TaskCompletionSource();
        var thread = new Thread(() =>
        {
            try { action(); done.SetResult(); }
            catch (Exception error) { done.SetException(error); }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        return done.Task;
    }

    private static void WpfPanel()
    {
        var (client, core, store) = NewClient();
        using (client)
        {
            var vm = new OwnerReviewViewModel(client, store) { GoalId = MockOwnerReviewCore.Goal };
            vm.LoadProposalCommand.Execute(null);
            for (var i = 0; i < 200 && !vm.HasProposal; i++) Thread.Sleep(15);
            True(vm.HasProposal, "proposal available for panel");
            var panel = new OwnerReviewPanel { DataContext = vm };
            panel.Measure(new System.Windows.Size(900, 1400));
            panel.Arrange(new System.Windows.Rect(0, 0, 900, 1400));
            panel.UpdateLayout();
            var identity = (ItemsControl)Find(panel, "OwnerReviewIdentityFields");
            var intent = (ItemsControl)Find(panel, "OwnerReviewIntentFields");
            Eq(vm.IdentityFields.Count, identity.Items.Count, "identity list bound");
            Eq(3, intent.Items.Count, "UNKNOWN pose/scene are correctly grouped as creative intent");
            var banner = (TextBlock)Find(panel, "OwnerReviewTransportBanner");
            True(banner.Text.Contains("TRANSPORT_SECURITY=BLOCKED", StringComparison.Ordinal), "banner shows blocked transport");
            Find(panel, "OwnerReviewPreview"); Find(panel, "OwnerReviewConfirm"); Find(panel, "OwnerReviewCommit"); Find(panel, "OwnerReviewCancel");
            var policy = (CheckBox)Find(panel, "OwnerReviewStaticStoryOptIn");
            True(policy.IsChecked != true, "static story is never selected by default");
            var confirm = (CheckBox)Find(panel, "OwnerReviewConfirm");
            True(confirm.IsChecked != true, "confirmation checkbox is never pre-checked");
            Eq(0, core.CountPath("/preview") + core.CountPath("/commit"), "rendering the panel performs no write");
            if (Environment.GetEnvironmentVariable("OWNER_REVIEW_SCREENSHOT_DIR") is { Length: > 0 } directory)
            {
                Directory.CreateDirectory(directory);
                var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(900, 1400, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
                bitmap.Render(panel);
                var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder();
                encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
                using var stream = File.Create(Path.Combine(directory, "owner-review-panel-synthetic.png"));
                encoder.Save(stream);
            }
        }
    }

    private static System.Windows.FrameworkElement Find(System.Windows.DependencyObject root, string automationId)
    {
        var queue = new Queue<System.Windows.DependencyObject>();
        queue.Enqueue(root);
        while (queue.Count > 0)
        {
            var node = queue.Dequeue();
            if (node is System.Windows.FrameworkElement element
                && System.Windows.Automation.AutomationProperties.GetAutomationId(element) == automationId)
                return element;
            foreach (var child in LogicalChildren(node)) queue.Enqueue(child);
        }
        throw new InvalidOperationException("control not found: " + automationId);
    }

    private static IEnumerable<System.Windows.DependencyObject> LogicalChildren(System.Windows.DependencyObject node)
    {
        if (node is System.Windows.Media.Visual or System.Windows.Media.Media3D.Visual3D)
        {
            var count = System.Windows.Media.VisualTreeHelper.GetChildrenCount(node);
            for (var i = 0; i < count; i++) yield return System.Windows.Media.VisualTreeHelper.GetChild(node, i);
        }
        foreach (var child in System.Windows.LogicalTreeHelper.GetChildren(node).OfType<System.Windows.DependencyObject>())
            yield return child;
    }
}
