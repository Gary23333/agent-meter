using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>仅保存页面周期，不保存本机账本或账户信息。</summary>
internal static class UsagePeriodPreferences
{
    public static bool Valid(string period) => period is "today" or "7d" or "30d" or "all";
    public static string Load(string directory)
    {
        try
        {
            using var file = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "usage-view.json")));
            var root = file.RootElement;
            if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("period", out var value) && value.ValueKind == JsonValueKind.String && Valid(value.GetString() ?? ""))
                return value.GetString()!;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or System.Security.SecurityException) { }
        return "today";
    }
    public static void Save(string directory, string period)
    {
        if (!Valid(period)) throw new ArgumentException("未知用量周期");
        Directory.CreateDirectory(directory);
        string temp = Path.Combine(directory, Path.GetRandomFileName()); bool created = false;
        try
        {
            using (var file = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { created = true; JsonSerializer.Serialize(file, new { period }); }
            File.Move(temp, Path.Combine(directory, "usage-view.json"), overwrite: true);
        }
        finally { try { if (created) File.Delete(temp); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { } }
    }
}
