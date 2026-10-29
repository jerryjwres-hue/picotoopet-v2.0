// P0-Q2 #140: synthetic contract tests; do not pretend to measure visual perception.
using PicotooPet.QualityObservation;
using System.Security.Cryptography;

static void Check(bool condition, string label)
{
    if (!condition) throw new InvalidOperationException("ASSERT_" + label);
}
static void Reject(Action action, string label)
{
    try { action(); }
    catch (InvalidOperationException) { return; }
    throw new InvalidOperationException("MUST_REJECT_" + label);
}
static InputManifest Manifest() => new("visual_review.input.v1",
    "64695948-fb1a-4793-815f-3f6ad4d4d536",
    [
        new(1, "shot1", "task1", "job/shot1.webm", new string('a', 64), 1024, 97, 4000, "cat enters"),
        new(2, "shot2", "task2", "job/shot2.webm", new string('b', 64), 1024, 97, 4000, "cat finds object"),
        new(3, "shot3", "task3", "job/shot3.webm", new string('c', 64), 1024, 97, 4000, "cat uses product")
    ]);
var good = Manifest();
ReviewPolicy.Validate(good);
Reject(() => ReviewPolicy.Validate(good with { Shots = good.Shots.Take(2).ToList() }), "COUNT");
Reject(() => ReviewPolicy.Validate(good with { Shots = [good.Shots[1], good.Shots[0], good.Shots[2]] }), "ORDER");
Reject(() => ReviewPolicy.Validate(good with { Shots = [good.Shots[0], good.Shots[1] with { TaskId = "task1" }, good.Shots[2]] }), "TASK_DUPLICATE");
Reject(() => ReviewPolicy.Validate(good with { Shots = [good.Shots[0] with { Sha256 = new string('0', 63) }, good.Shots[1], good.Shots[2]] }), "SHA");
Reject(() => ReviewPolicy.Validate(good with { Shots = [good.Shots[0], good.Shots[1] with { RelativePath = "job/shot1.webm" }, good.Shots[2]] }), "PATH_DUPLICATE");
Reject(() => ReviewPolicy.Validate(good with { Shots = [good.Shots[0] with { ExpectedFrames = 0 }, good.Shots[1], good.Shots[2]] }), "FRAMES");
Check(ReviewPolicy.ValidateLocalEndpoint("http://192.168.1.15:11434", "qwen3-vl:4b", true)
    == "http://192.168.1.15:11434", "PRIVATE_LAN");
Reject(() => ReviewPolicy.ValidateLocalEndpoint("http://1.1.1.1:11434", "qwen3-vl:4b", true), "PUBLIC_IP");
Reject(() => ReviewPolicy.ValidateLocalEndpoint("https://192.168.1.15:11434", "qwen3-vl:4b", true), "UNAPPROVED_PROTOCOL");
Reject(() => ReviewPolicy.ValidateLocalEndpoint("http://mac.local:11434", "qwen3-vl:4b", true), "DNS_DISALLOWED");
Reject(() => ReviewPolicy.ValidateLocalEndpoint("http://192.168.1.15:11434", "qwen3-vl:4b", false), "NO_CONSENT");
var root = Path.Combine(Path.GetTempPath(), "p0q2-observer-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    Reject(() => ReviewPolicy.SafeSource(root, "../escape.webm"), "TRAVERSAL");
    Reject(() => ReviewPolicy.SafeSource(root, "C:\\escape.webm"), "DRIVE");
    Reject(() => ReviewPolicy.SafeOutput(root, Path.Combine(root, "evidence")), "OUTPUT_INSIDE_SOURCE");
    var file = Path.Combine(root, "shot.webm");
    File.WriteAllBytes(file, Enumerable.Repeat((byte)0x33, 2048).ToArray());
    Check(ReviewPolicy.SafeSource(root, "shot.webm") == Path.GetFullPath(file), "SOURCE_ACCESS");
    var shaBefore = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file)));
    Reject(() => ReviewPolicy.SafeSource(root, "missing.webm"), "MISSING_SOURCE");
    Check(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file))) == shaBefore, "IMMUTABLE_SOURCE");
}
finally { Directory.Delete(root, recursive: true); }

// Mock cat/scarf/lamp descriptions test parser routing, NOT model quality.
var known = new HashSet<string>(StringComparer.Ordinal) { "frame_01.png", "frame_04.png", "frame_07.png" };
var drift = """
{"flags":[{"shot_order":2,"category":"scarf_inconsistency","severity":"high","evidence_filename":"frame_04.png","rationale":"mock changed scarf","confidence":0.72},{"shot_order":3,"category":"floating_object","severity":"medium","evidence_filename":"frame_07.png","rationale":"mock floating lamp","confidence":0.66}],"reviewer_disagreement":true}
""";
var result = ReviewPolicy.ParseAdvisory(drift, known);
Check(result.Status == "REJECT_SUSPECT" && result.Concerns.Count == 2, "SUSPECT_NOT_ACCEPT");
Check(result.Disagreement == "FLAGGED", "DISAGREEMENT");
Check(ReviewPolicy.ParseAdvisory("""{"flags":[],"reviewer_disagreement":false}""", known).Status == "ADVISORY_REVIEW", "NO_ACCEPT");
Reject(() => ReviewPolicy.ParseAdvisory(drift.Replace("frame_07.png", "../../outside.png", StringComparison.Ordinal), known), "UNGROUNDED");
Reject(() => ReviewPolicy.ParseAdvisory(drift.Replace("floating_object", "ACCEPT", StringComparison.Ordinal), known), "PROMOTE");
Reject(() => ReviewPolicy.ParseAdvisory(drift.Replace("0.66", "1.1", StringComparison.Ordinal), known), "CONFIDENCE");
Console.WriteLine("P0_Q2_VISUAL_REVIEW_POLICY=PASS");
Console.WriteLine("P0_Q2_VLM_MOCK_DISAGREEMENT=FLAGGED; PERCEPTUAL_ACCURACY=UNVERIFIED");
Console.WriteLine("P0_Q2_REAL_MEDIA=UNVERIFIED; GPU_POST=0; C011_AUTHORITY=UNCHANGED");
