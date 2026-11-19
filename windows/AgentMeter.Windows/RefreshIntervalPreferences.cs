using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>仅保存定时刷新间隔；首次安装使用 15 分钟。</summary>
internal static class RefreshIntervalPreferences
{
    public static readonly int[] Choices = [5, 15, 30];
    public static bool Valid(int minutes) => Choices.Contains(minutes);
    public static int Load(string directory)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "refresh.json")));
            var root = document.RootElement;
            return root.ValueKind == JsonValueKind.Object && root.TryGetProperty("minutes", out var value) &&
                   value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int minutes) && Valid(minutes) ? minutes : 15;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or System.Security.SecurityException)
        { return 15; }
    }
    public static void Save(string directory, int minutes)
    {
        if (!Valid(minutes)) throw new ArgumentException("刷新间隔无效");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true; JsonSerializer.Serialize(file, new { minutes });
            }
            File.Move(temporary, Path.Combine(directory, "refresh.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
