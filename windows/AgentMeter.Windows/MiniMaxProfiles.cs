using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record MiniMaxProfile(Guid Id, string Label, string Region);

internal interface IMiniMaxVault
{
    void Write(Guid id, string secret);
    string? Read(Guid id);
    void Delete(Guid id);
}

internal sealed class WindowsMiniMaxVault : IMiniMaxVault
{
    public void Write(Guid id, string secret) => CredentialVault.Write("minimax", id, secret);
    public string? Read(Guid id) => CredentialVault.Read("minimax", id);
    public void Delete(Guid id) => CredentialVault.Delete("minimax", id);
}

/// <summary>账户文件只保存名称、区域和随机标识；密钥保存在 Windows 凭据管理器。</summary>
internal static class MiniMaxProfiles
{
    const int MaxAccounts = 5;
    public static List<MiniMaxProfile> Load(string directory)
    {
        string path = Path.Combine(directory, "minimax-accounts.json");
        try
        {
            var info = new FileInfo(path);
            if (info.Length > 65536) throw new InvalidDataException("账户列表过大");
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("version", out var version) ||
                version.ValueKind != JsonValueKind.Number || !version.TryGetInt32(out int n) || n != 1 ||
                !root.TryGetProperty("accounts", out var accounts) || accounts.ValueKind != JsonValueKind.Array ||
                root.EnumerateObject().Count() != 2 || root.EnumerateObject().Any(p => p.Name is not ("version" or "accounts")))
                throw new InvalidDataException("账户列表格式不正确");
            var result = new List<MiniMaxProfile>();
            foreach (var item in accounts.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object || item.EnumerateObject().Count() != 3 ||
                    item.EnumerateObject().Any(p => p.Name is not ("id" or "label" or "region")) ||
                    !item.TryGetProperty("id", out var id) || id.ValueKind != JsonValueKind.String ||
                    !Guid.TryParseExact(id.GetString(), "N", out var parsed) ||
                    !item.TryGetProperty("label", out var label) || label.ValueKind != JsonValueKind.String ||
                    !item.TryGetProperty("region", out var region) || region.ValueKind != JsonValueKind.String)
                    throw new InvalidDataException("账户列表格式不正确");
                result.Add(new MiniMaxProfile(parsed, label.GetString() ?? "", region.GetString() ?? ""));
            }
            Validate(result);
            return result;
        }
        catch (FileNotFoundException) { return []; }
        catch (DirectoryNotFoundException) { return []; }
        catch (JsonException ex) { throw new InvalidDataException("账户列表格式不正确", ex); }
    }

    static void Validate(IReadOnlyCollection<MiniMaxProfile> profiles)
    {
        if (profiles.Count > MaxAccounts) throw new InvalidDataException("最多添加 5 个 MiniMax 账户");
        var ids = new HashSet<Guid>(); var labels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var profile in profiles)
        {
            string label = profile.Label.Trim();
            if (profile.Id == Guid.Empty || !ids.Add(profile.Id) || label.Length is < 1 or > 32 ||
                label.Any(char.IsControl) || !labels.Add(label) || profile.Region is not ("cn" or "global"))
                throw new InvalidDataException("账户名称、区域或标识无效或重复");
        }
    }

    static void Save(string directory, IReadOnlyCollection<MiniMaxProfile> profiles)
    {
        Validate(profiles);
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, new { version = 1, accounts = profiles.Select(profile =>
                    new { id = profile.Id.ToString("N"), label = profile.Label.Trim(), region = profile.Region }) });
            }
            File.Move(temporary, Path.Combine(directory, "minimax-accounts.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }

    public static MiniMaxProfile Add(string directory, string label, string region, string secret, IMiniMaxVault vault)
    {
        var before = Load(directory);
        var profile = new MiniMaxProfile(Guid.NewGuid(), label.Trim(), region);
        var after = before.Append(profile).ToList();
        Validate(after);
        // 先记录随机标识：若进程中途退出，缺失的凭据仍可在列表中被发现并清理。
        Save(directory, after);
        try { vault.Write(profile.Id, secret); }
        catch
        {
            try { Save(directory, before); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
            throw;
        }
        return profile;
    }

    public static void Remove(string directory, Guid id, IMiniMaxVault vault)
    {
        var before = Load(directory);
        if (before.All(profile => profile.Id != id)) throw new InvalidDataException("账户不存在");
        // 先删除密钥，意外退出时只会留下可见的无凭据条目，不会留下隐藏的密钥。
        vault.Delete(id);
        Save(directory, before.Where(profile => profile.Id != id).ToList());
    }
}
