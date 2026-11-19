using System.ComponentModel;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>将凭据仅放入后端子进程的标准输入，不放进命令行或账户文件。</summary>
internal static class MiniMaxAccountInput
{
    public static string? Build(string directory, IMiniMaxVault vault)
    {
        var profiles = MiniMaxProfiles.Load(directory);
        if (profiles.Count == 0 && !File.Exists(Path.Combine(directory, "minimax-accounts.json"))) return null;
        var accounts = new List<object>();
        foreach (var profile in profiles)
        {
            string? key;
            try { key = vault.Read(profile.Id); }
            catch (Exception ex) when (ex is Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { key = null; }
            if (key is not null && (key.Length == 0 || key.Length > 1280 || key.Any(char.IsControl))) key = null;
            accounts.Add(new { label = profile.Label, region = profile.Region, key });
        }
        return JsonSerializer.Serialize(new { minimax_accounts = accounts });
    }
}
