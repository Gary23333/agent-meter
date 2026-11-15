using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>只保存账户查询开关，不保存凭据或账户数据。</summary>
internal sealed record AccountPreferences(bool Codex, bool Kimi, bool Claude, bool MiniMax = false, bool DeepSeek = false, bool WorkBuddy = false, bool ZCode = false, bool Volcengine = false, bool MiMo = false)
{
    public static AccountPreferences Enabled => new(true, true, true);
    public static AccountPreferences Disabled => new(false, false, false);
    public static string DefaultDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AgentMeter");

    public static AccountPreferences Load(string directory)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "preferences.json")));
            var root = document.RootElement;
            bool minimax = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("minimax", out _)
                ? ReadBoolean(root, "minimax") : false;
            bool deepseek = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("deepseek", out _)
                ? ReadBoolean(root, "deepseek") : false;
            bool workbuddy = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("workbuddy", out _)
                ? ReadBoolean(root, "workbuddy") : false;
            bool zcode = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("zcode", out _) ? ReadBoolean(root, "zcode") : false;
            bool volcengine = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("volcengine", out _) ? ReadBoolean(root, "volcengine") : false;
            bool mimo = root.ValueKind == JsonValueKind.Object && root.TryGetProperty("mimo", out _) ? ReadBoolean(root, "mimo") : false;
            return new AccountPreferences(ReadBoolean(root, "codex"), ReadBoolean(root, "kimi"), ReadBoolean(root, "claude"), minimax, deepseek, workbuddy, zcode, volcengine, mimo);
        }
        catch (FileNotFoundException) { return Enabled; }
        catch (DirectoryNotFoundException) { return Enabled; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or System.Security.SecurityException)
        {
            // 已存在的设置无法读取时关闭账户查询，避免意外恢复曾被关闭的来源。
            return Disabled;
        }
    }

    static bool ReadBoolean(JsonElement root, string key)
    {
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(key, out var value) ||
            value.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw new JsonException("invalid preference");
        return value.GetBoolean();
    }

    public void Save(string directory)
    {
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            var values = new Dictionary<string, bool> { ["codex"] = Codex, ["kimi"] = Kimi, ["claude"] = Claude,
                ["minimax"] = MiniMax, ["deepseek"] = DeepSeek, ["workbuddy"] = WorkBuddy, ["zcode"] = ZCode, ["volcengine"] = Volcengine, ["mimo"] = MiMo };
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, values);
            }
            File.Move(temporary, Path.Combine(directory, "preferences.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
