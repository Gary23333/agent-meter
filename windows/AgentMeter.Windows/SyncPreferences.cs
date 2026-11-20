using System.Security.Cryptography;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>本机的同步空间配置；主密钥不在这里，它在 Windows 凭据管理器。</summary>
internal sealed record SyncPreferences(string BaseUrl, string SpaceId, string DeviceId, long? LastSyncAt)
{
    public const string FileName = "sync.json";
    public static string DefaultDirectory => AccountPreferences.DefaultDirectory;

    public static bool IsIdentifier(string? value) =>
        value is { Length: 32 } && value.All(ch => ch is >= '0' and <= '9' or >= 'a' and <= 'f');

    public static string NewIdentifier() => Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();

    public static SyncPreferences? Load(string directory)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, FileName)));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            string? url = root.TryGetProperty("base_url", out var u) && u.ValueKind == JsonValueKind.String ? u.GetString() : null;
            string? space = root.TryGetProperty("space_id", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
            string? device = root.TryGetProperty("device_id", out var d) && d.ValueKind == JsonValueKind.String ? d.GetString() : null;
            long? last = root.TryGetProperty("last_sync_at", out var l) && l.ValueKind == JsonValueKind.Number && l.TryGetInt64(out long value) ? value : null;
            if (string.IsNullOrWhiteSpace(url) || url.Length > 200 || !IsIdentifier(space) || !IsIdentifier(device)) return null;
            return new SyncPreferences(url, space!, device!, last);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or System.Security.SecurityException)
        {
            return null;
        }
    }

    public void Save(string directory)
    {
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            var values = new Dictionary<string, object?>
            {
                ["base_url"] = BaseUrl, ["space_id"] = SpaceId, ["device_id"] = DeviceId, ["last_sync_at"] = LastSyncAt
            };
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, values);
            }
            File.Move(temporary, Path.Combine(directory, FileName), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }

    public static void Delete(string directory)
    {
        try { File.Delete(Path.Combine(directory, FileName)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
    }

    public static bool ValidBaseUrl(string value)
    {
        if (!Uri.TryCreate(value.Trim(), UriKind.Absolute, out var uri)) return false;
        if (!string.IsNullOrEmpty(uri.UserInfo)) return false;
        if (uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)) return true;
        return uri.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase) &&
               uri.Host is "127.0.0.1" or "localhost" or "::1";
    }
}
