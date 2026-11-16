using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>保存桌宠显示、形象、位置及视线跟随选项；默认不显示且不跟随。</summary>
internal sealed record PetPreferences(bool Enabled, string Pack, int? X, int? Y, bool FollowCursor = false)
{
    public static PetPreferences Default => new(false, "mochi", null, null);
    public static PetPreferences Load(string directory)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "pet-settings.json")));
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("enabled", out var enabled) ||
                enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
                !root.TryGetProperty("pack", out var pack) || pack.ValueKind != JsonValueKind.String ||
                !ValidPack(pack.GetString())) return Default;
            int? Coordinate(string name)
            {
                if (!root.TryGetProperty(name, out var value) || value.ValueKind == JsonValueKind.Null) return null;
                return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int n) && n is >= -100000 and <= 100000 ? n : null;
            }
            bool follow = root.TryGetProperty("follow_cursor", out var cursor) && cursor.ValueKind == JsonValueKind.True;
            return new PetPreferences(enabled.GetBoolean(), pack.GetString()!, Coordinate("x"), Coordinate("y"), follow);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or System.Security.SecurityException) { return Default; }
    }
    public void Save(string directory)
    {
        if (!ValidPack(Pack) || X is < -100000 or > 100000 || Y is < -100000 or > 100000)
            throw new InvalidDataException("桌宠设置无效");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true; JsonSerializer.Serialize(file, new { enabled = Enabled, pack = Pack, x = X, y = Y, follow_cursor = FollowCursor });
            }
            File.Move(temporary, Path.Combine(directory, "pet-settings.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
    internal static bool ValidPack(string? pack) => pack is "mochi" or "bit" or "gauge" or "cat" or "bot" or "tibo" or "blob";
}
