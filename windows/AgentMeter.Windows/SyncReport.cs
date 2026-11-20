using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record SyncRunResult(bool Uploaded, int Devices, IReadOnlyList<string> Imported,
                                    IReadOnlyList<string> Failed)
{
    public static SyncRunResult? Read(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                (root.TryGetProperty("status", out var status) && status.ValueKind == JsonValueKind.String &&
                 status.GetString() == "error")) return null;
            bool uploaded = root.TryGetProperty("uploaded", out var u) && u.ValueKind == JsonValueKind.True;
            int devices = root.TryGetProperty("devices", out var d) && d.ValueKind == JsonValueKind.Number &&
                d.TryGetInt32(out int count) ? count : 0;
            var imported = ReadStrings(root, "imported");
            var failed = ReadStrings(root, "failed");
            return new SyncRunResult(uploaded, devices, imported, failed);
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException) { return null; }
    }

    static IReadOnlyList<string> ReadStrings(JsonElement root, string key)
    {
        if (!root.TryGetProperty(key, out var value) || value.ValueKind != JsonValueKind.Array) return [];
        var list = new List<string>();
        foreach (var item in value.EnumerateArray())
            if (item.ValueKind == JsonValueKind.String) list.Add(item.GetString() ?? "");
        return list;
    }
}

internal sealed record SyncDeviceRow(string DeviceId, long Size, long Version, long? UpdatedAt)
{
    public string ShortId => DeviceId.Length == 32 ? DeviceId[..8] : DeviceId;
    public string Updated => UpdatedAt is long value
        ? DateTimeOffset.FromUnixTimeSeconds(value).ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)
        : "—";
    public string SizeText => Size < 1024 ? $"{Size} B" : Size < 1024 * 1024 ? $"{Size / 1024.0:0.0} KB" : $"{Size / 1024.0 / 1024.0:0.0} MB";

    public static IReadOnlyList<SyncDeviceRow> Read(string json)
    {
        var rows = new List<SyncDeviceRow>();
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                (root.TryGetProperty("status", out var status) && status.ValueKind == JsonValueKind.String &&
                 status.GetString() == "error")) return rows;
            if (!root.TryGetProperty("devices", out var devices) || devices.ValueKind != JsonValueKind.Array) return rows;
            foreach (var item in devices.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object) continue;
                string? id = item.TryGetProperty("device_id", out var i) && i.ValueKind == JsonValueKind.String ? i.GetString() : null;
                if (id is null || id.Length != 32) continue;
                long size = item.TryGetProperty("size", out var s) && s.TryGetInt64(out long sizeValue) ? sizeValue : 0;
                long version = item.TryGetProperty("version", out var v) && v.TryGetInt64(out long versionValue) ? versionValue : 0;
                long? updated = item.TryGetProperty("updated_at", out var u) && u.ValueKind == JsonValueKind.Number &&
                    u.TryGetDouble(out double updatedValue) ? (long)updatedValue : null;
                rows.Add(new SyncDeviceRow(id, size, version, updated));
            }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException) { }
        return rows;
    }
}
