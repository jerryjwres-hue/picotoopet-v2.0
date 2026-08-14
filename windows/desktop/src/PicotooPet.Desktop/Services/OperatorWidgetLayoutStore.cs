using System.IO;
using System.Text.Json;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Services;

/// <summary>只持久化首页组件顺序和显隐偏好；文件不保存凭据或任意执行参数。</summary>
public sealed class OperatorWidgetLayoutStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    private readonly string _path;

    /// <summary>创建当前用户级组件布局存储。</summary>
    public OperatorWidgetLayoutStore(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        _path = path;
    }

    /// <summary>安全读取布局；损坏、拒绝访问或不兼容内容均回退固定默认目录。</summary>
    public OperatorWidgetLayout LoadOrDefault()
    {
        if (!File.Exists(_path))
        {
            return OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
        }

        try
        {
            var json   = File.ReadAllText(_path);
            var layout = JsonSerializer.Deserialize<OperatorWidgetLayout>(json, JsonOptions);
            return layout is null
                ? OperatorWidgetLayout.Normalize(requestedWidgetIds: null)
                : OperatorWidgetLayout.Normalize(layout.WidgetIds, layout.HiddenWidgetIds);
        }
        catch (IOException)
        {
            return OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
        }
        catch (UnauthorizedAccessException)
        {
            return OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
        }
        catch (JsonException)
        {
            return OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
        }
        catch (NotSupportedException)
        {
            return OperatorWidgetLayout.Normalize(requestedWidgetIds: null);
        }
    }

    /// <summary>使用临时文件原子替换；保存失败只影响偏好，不允许拖垮主界面。</summary>
    public bool TrySave(OperatorWidgetLayout layout)
    {
        ArgumentNullException.ThrowIfNull(layout);
        var normalized = OperatorWidgetLayout.Normalize(layout.WidgetIds, layout.HiddenWidgetIds);
        var temporary  = _path + ".tmp";

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path) ?? ".");
            File.WriteAllText(temporary, JsonSerializer.Serialize(normalized, JsonOptions));
            File.Move(temporary, _path, overwrite: true);
            return true;
        }
        catch (IOException)
        {
            TryDeleteTemporary(temporary);
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            TryDeleteTemporary(temporary);
            return false;
        }
        catch (JsonException)
        {
            TryDeleteTemporary(temporary);
            return false;
        }
        catch (NotSupportedException)
        {
            TryDeleteTemporary(temporary);
            return false;
        }
    }

    private static void TryDeleteTemporary(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 临时偏好文件清理失败不会影响业务运行；下一次保存会覆盖同名文件。
        }
        catch (UnauthorizedAccessException)
        {
            // 权限错误只影响偏好文件，不扩大成首页或任务执行故障。
        }
    }
}
