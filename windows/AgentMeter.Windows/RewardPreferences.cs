using System.Text.Json;
using System.Text.RegularExpressions;

namespace AgentMeter.Windows;

internal sealed record RewardSettings(bool Enabled, string ClaimTime)
{
    public static RewardSettings Default => new(false, "08:00");
}

/// <summary>每日积分领取设置：只保存开关与领取时刻，不含任何会话或凭据。</summary>
internal static class RewardPreferences
{
    static readonly Regex Clock = new(@"^([01][0-9]|2[0-3]):([0-5][0-9])$", RegexOptions.CultureInvariant);
    public static IReadOnlyList<string> Choices { get; } = BuildChoices();

    static IReadOnlyList<string> BuildChoices()
    {
        var values = new List<string> { "00:05" };
        for (int hour = 6; hour <= 23; hour++) { values.Add($"{hour:00}:00"); values.Add($"{hour:00}:30"); }
        return values;
    }

    public static bool ValidClock(string? value) => value is not null && Clock.IsMatch(value);

    /// <summary>读不到或格式损坏时保持关闭：绝不能因为文件坏掉就自动开始扣请求。</summary>
    public static RewardSettings Load(string directory)
    {
        string path = Path.Combine(directory, "auto-claim.json");
        try
        {
            if (new FileInfo(path).Length > 16384) return RewardSettings.Default;
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object || root.EnumerateObject().Count() != 3 ||
                root.GetProperty("schema").GetInt32() != 1) return RewardSettings.Default;
            var enabled = root.GetProperty("enabled");
            var clock = root.GetProperty("claim_time");
            if (enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False) || clock.ValueKind != JsonValueKind.String)
                return RewardSettings.Default;
            string time = clock.GetString()!;
            if (!ValidClock(time)) return RewardSettings.Default;
            return new(enabled.GetBoolean(), time);
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException or IOException or
            UnauthorizedAccessException or System.Security.SecurityException or JsonException or InvalidOperationException or
            KeyNotFoundException or FormatException or OverflowException or ArgumentException)
        { return RewardSettings.Default; }
    }

    public static void Save(string directory, RewardSettings settings)
    {
        if (!ValidClock(settings.ClaimTime)) throw new ArgumentException("领取时刻格式无效");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName()); bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                JsonSerializer.Serialize(file, new { schema = 1, enabled = settings.Enabled, claim_time = settings.ClaimTime });
            File.Move(temporary, Path.Combine(directory, "auto-claim.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
