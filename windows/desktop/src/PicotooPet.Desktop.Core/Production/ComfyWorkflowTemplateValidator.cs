using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>冻结 2.3.20.1 ComfyUI API graph；只允许源码模板里的 core node 与固定模型。</summary>
public static class ComfyWorkflowTemplateValidator
{
    public const string T2VWorkflowId = "comfy.wan22.ti2v5b.t2v.v1";
    public const string I2VWorkflowId = "comfy.wan22.ti2v5b.i2v.v1";
    public const string TrustedInputPlaceholder = "__PICOTOO_TRUSTED_INPUT_IMAGE__";

    private const string PositivePromptPlaceholder = "__PICOTOO_POSITIVE_PROMPT__";
    private const string SeedPlaceholder = "__PICOTOO_SEED__";
    private const string WidthPlaceholder = "__PICOTOO_WIDTH__";
    private const string HeightPlaceholder = "__PICOTOO_HEIGHT__";
    private const string LengthPlaceholder = "__PICOTOO_LENGTH__";
    private const string FpsPlaceholder = "__PICOTOO_FPS__";
    private const string FilenamePrefixPlaceholder = "__PICOTOO_FILENAME_PREFIX__";

    // ── Analyzer-safe immutable node surface; reused for every template node ─
    private static readonly string[] RequiredNodeMembers = ["class_type", "inputs"];

    private static readonly HashSet<string> BaseClasses = new(StringComparer.Ordinal)
    {
        "UNETLoader",
        "CLIPLoader",
        "VAELoader",
        "ModelSamplingSD3",
        "CLIPTextEncode",
        "Wan22ImageToVideoLatent",
        "KSampler",
        "VAEDecode",
        "SaveWEBM",
    };

    /// <summary>验证 workflow 结构、core node allowlist 与 loader 固定值。</summary>
    public static void Validate(string workflowId, string json)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workflowId);
        ArgumentException.ThrowIfNullOrWhiteSpace(json);
        using var document = JsonDocument.Parse(json, new JsonDocumentOptions
        {
            AllowTrailingCommas = false,
            CommentHandling = JsonCommentHandling.Disallow,
            MaxDepth = 64,
        });
        if (document.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("COMFY_TEMPLATE_ROOT_INVALID");
        }

        var allowed = AllowedClasses(workflowId);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in document.RootElement.EnumerateObject())
        {
            if (!int.TryParse(property.Name, out _)
                || property.Value.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("COMFY_TEMPLATE_NODE_ID_INVALID");
            }
            var members = property.Value.EnumerateObject().Select(item => item.Name).ToHashSet(StringComparer.Ordinal);
            if (!members.SetEquals(RequiredNodeMembers))
            {
                throw new InvalidDataException("COMFY_TEMPLATE_NODE_SHAPE_INVALID");
            }
            var classType = property.Value.GetProperty("class_type").GetString()
                ?? throw new InvalidDataException("COMFY_TEMPLATE_CLASS_MISSING");
            if (!allowed.Contains(classType))
            {
                throw new InvalidDataException($"COMFY_TEMPLATE_CLASS_FORBIDDEN:{classType}");
            }
            if (property.Value.GetProperty("inputs").ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("COMFY_TEMPLATE_INPUTS_INVALID");
            }
            seen.Add(classType);
        }
        if (!seen.SetEquals(allowed))
        {
            throw new InvalidDataException("COMFY_TEMPLATE_CLASS_SET_MISMATCH");
        }

        AssertLoader(document.RootElement, "UNETLoader", "unet_name", "wan2.2_ti2v_5B_fp16.safetensors");
        AssertLoader(document.RootElement, "CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors");
        AssertLoader(document.RootElement, "VAELoader", "vae_name", "wan2.2_vae.safetensors");
        AssertPlaceholder(document.RootElement, "CLIPTextEncode", "text", PositivePromptPlaceholder);
        AssertPlaceholder(document.RootElement, "KSampler", "seed", SeedPlaceholder);
        AssertPlaceholder(document.RootElement, "Wan22ImageToVideoLatent", "width", WidthPlaceholder);
        AssertPlaceholder(document.RootElement, "Wan22ImageToVideoLatent", "height", HeightPlaceholder);
        AssertPlaceholder(document.RootElement, "Wan22ImageToVideoLatent", "length", LengthPlaceholder);
        AssertPlaceholder(document.RootElement, "SaveWEBM", "fps", FpsPlaceholder);
        AssertPlaceholder(document.RootElement, "SaveWEBM", "filename_prefix", FilenamePrefixPlaceholder);
        if (workflowId == I2VWorkflowId)
        {
            AssertPlaceholder(document.RootElement, "LoadImage", "image", TrustedInputPlaceholder);
        }
    }

    /// <summary>在已验证模板上只替换声明过的安全 slot；其余 graph 不可修改。</summary>
    public static JsonObject Bind(
        string workflowId,
        string json,
        ProductionTaskPlanRecord task,
        string filenamePrefix,
        string? trustedInputImage = null)
    {
        Validate(workflowId, json);
        ArgumentNullException.ThrowIfNull(task);
        if (!string.Equals(task.WorkflowId, workflowId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("COMFY_PLAN_WORKFLOW_MISMATCH");
        }
        if (string.IsNullOrWhiteSpace(filenamePrefix)
            || filenamePrefix.Contains("..", StringComparison.Ordinal)
            || Path.IsPathRooted(filenamePrefix))
        {
            throw new InvalidDataException("COMFY_FILENAME_PREFIX_INVALID");
        }

        var root = JsonNode.Parse(json)?.AsObject()
            ?? throw new InvalidDataException("COMFY_TEMPLATE_ROOT_INVALID");
        ReplaceInput(root, "CLIPTextEncode", "text", PositivePromptPlaceholder, JsonValue.Create(task.PositivePrompt));
        ReplaceInput(root, "KSampler", "seed", SeedPlaceholder, JsonValue.Create(task.Seed));
        ReplaceInput(root, "Wan22ImageToVideoLatent", "width", WidthPlaceholder, JsonValue.Create(task.Width));
        ReplaceInput(root, "Wan22ImageToVideoLatent", "height", HeightPlaceholder, JsonValue.Create(task.Height));
        ReplaceInput(root, "Wan22ImageToVideoLatent", "length", LengthPlaceholder, JsonValue.Create(task.FrameCount));
        ReplaceInput(root, "SaveWEBM", "fps", FpsPlaceholder, JsonValue.Create(task.Fps));
        ReplaceInput(root, "SaveWEBM", "filename_prefix", FilenamePrefixPlaceholder, JsonValue.Create(filenamePrefix));
        if (workflowId == I2VWorkflowId)
        {
            if (string.IsNullOrWhiteSpace(trustedInputImage)
                || trustedInputImage.Contains("..", StringComparison.Ordinal)
                || Path.IsPathRooted(trustedInputImage))
            {
                throw new InvalidDataException("COMFY_TRUSTED_INPUT_INVALID");
            }
            ReplaceInput(root, "LoadImage", "image", TrustedInputPlaceholder, JsonValue.Create(trustedInputImage));
        }
        return root;
    }

    private static HashSet<string> AllowedClasses(string workflowId)
    {
        if (workflowId == T2VWorkflowId)
        {
            return new HashSet<string>(BaseClasses, StringComparer.Ordinal);
        }
        if (workflowId == I2VWorkflowId)
        {
            var allowed = new HashSet<string>(BaseClasses, StringComparer.Ordinal) { "LoadImage" };
            return allowed;
        }
        throw new InvalidDataException("COMFY_WORKFLOW_ID_FORBIDDEN");
    }

    private static void AssertLoader(JsonElement root, string classType, string field, string expected)
    {
        var node = FindSingle(root, classType);
        var actual = node.GetProperty("inputs").GetProperty(field).GetString();
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
        {
            throw new InvalidDataException($"COMFY_MODEL_BINDING_MISMATCH:{classType}");
        }
    }

    private static void AssertPlaceholder(JsonElement root, string classType, string field, string expected)
    {
        var candidates = root.EnumerateObject()
            .Select(item => item.Value)
            .Where(node => string.Equals(node.GetProperty("class_type").GetString(), classType, StringComparison.Ordinal))
            .Where(node => node.GetProperty("inputs").TryGetProperty(field, out var value)
                && value.ValueKind == JsonValueKind.String
                && string.Equals(value.GetString(), expected, StringComparison.Ordinal))
            .ToArray();
        if (candidates.Length != 1)
        {
            throw new InvalidDataException($"COMFY_TEMPLATE_SLOT_INVALID:{classType}.{field}");
        }
    }

    private static JsonElement FindSingle(JsonElement root, string classType)
    {
        var nodes = root.EnumerateObject()
            .Select(item => item.Value)
            .Where(node => string.Equals(node.GetProperty("class_type").GetString(), classType, StringComparison.Ordinal))
            .ToArray();
        return nodes.Length == 1
            ? nodes[0]
            : throw new InvalidDataException($"COMFY_TEMPLATE_CLASS_CARDINALITY:{classType}");
    }

    private static void ReplaceInput(
        JsonObject root,
        string classType,
        string field,
        string expectedPlaceholder,
        JsonNode? replacement)
    {
        var matches = root
            .Where(item => item.Value is JsonObject node
                && string.Equals(node["class_type"]?.GetValue<string>(), classType, StringComparison.Ordinal)
                && node["inputs"] is JsonObject inputs
                && string.Equals(inputs[field]?.GetValue<string>(), expectedPlaceholder, StringComparison.Ordinal))
            .Select(item => (JsonObject)item.Value!)
            .ToArray();
        if (matches.Length != 1)
        {
            throw new InvalidDataException($"COMFY_TEMPLATE_SLOT_INVALID:{classType}.{field}");
        }
        ((JsonObject)matches[0]["inputs"]!)[field] = replacement;
    }
}