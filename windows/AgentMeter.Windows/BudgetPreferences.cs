using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record BudgetSettings(bool Enabled, bool AlertsEnabled, decimal? Daily, decimal? Weekly, decimal Multiplier)
{
    public static BudgetSettings Default => new(false, false, null, null, 2m);
}

/// <summary>预算只保存估算阈值，不包含账户凭据或会话内容。</summary>
internal static class BudgetPreferences
{
    const decimal Maximum = 1_000_000_000m;
    public static BudgetSettings Load(string directory)
    {
        string path = Path.Combine(directory, "budget-windows.json");
        try
        {
            if (new FileInfo(path).Length > 16384) throw new InvalidDataException("预算设置文件过大");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            string[] keys = ["schema", "enabled", "alerts_enabled", "daily_cny", "weekly_cny", "anomaly_multiplier"];
            if (root.ValueKind != JsonValueKind.Object || root.EnumerateObject().Count() != keys.Length ||
                root.EnumerateObject().Any(item => !keys.Contains(item.Name)) || root.GetProperty("schema").GetInt32() != 1)
                throw new InvalidDataException("预算设置格式错误");
            bool enabled = root.GetProperty("enabled").GetBoolean(), alerts = root.GetProperty("alerts_enabled").GetBoolean();
            decimal? ReadAmount(string key)
            {
                var value = root.GetProperty(key);
                if (value.ValueKind == JsonValueKind.Null) return null;
                if (value.ValueKind != JsonValueKind.String || !TryAmount(value.GetString(), out var parsed)) throw new InvalidDataException("预算金额无效");
                return parsed;
            }
            var daily = ReadAmount("daily_cny"); var weekly = ReadAmount("weekly_cny");
            var multiplier = ReadAmount("anomaly_multiplier");
            if (!multiplier.HasValue || multiplier <= 0 || multiplier > 100) throw new InvalidDataException("异常倍率无效");
            return new(enabled, alerts, daily, weekly, multiplier.Value);
        }
        catch (FileNotFoundException) { return BudgetSettings.Default; }
        catch (DirectoryNotFoundException) { return BudgetSettings.Default; }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or OverflowException)
        { throw new InvalidDataException("预算设置格式错误", ex); }
    }
    public static bool TryAmount(string? input, out decimal value) => decimal.TryParse(input?.Trim(), NumberStyles.AllowDecimalPoint | NumberStyles.AllowLeadingSign,
        CultureInfo.InvariantCulture, out value) && value >= 0 && value <= Maximum;
    public static void Save(string directory, BudgetSettings settings)
    {
        if (settings.Daily is < 0 or > Maximum || settings.Weekly is < 0 or > Maximum || settings.Multiplier is <= 0 or > 100)
            throw new InvalidDataException("预算金额或异常倍率无效");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName()); bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, new { schema = 1, enabled = settings.Enabled, alerts_enabled = settings.AlertsEnabled,
                    daily_cny = settings.Daily?.ToString(CultureInfo.InvariantCulture), weekly_cny = settings.Weekly?.ToString(CultureInfo.InvariantCulture),
                    anomaly_multiplier = settings.Multiplier.ToString(CultureInfo.InvariantCulture) });
            }
            File.Move(temporary, Path.Combine(directory, "budget-windows.json"), overwrite: true);
        }
        finally { try { if (created) File.Delete(temporary); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { } }
    }
}
