using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>用户输入的 GLM Coding Plan 密钥只保存于 Windows 凭据管理器。</summary>
internal static class ZCodeKeyStore
{
    static readonly Guid Slot = new("75c9230f-c2e4-497a-af2b-6bfa5e5f6c25");
    public static bool IsValid(string? key) => key is { Length: > 0 and <= 1280 } && key.All(c => c is >= '!' and <= '~');
    public static string? Read() { string? key = CredentialVault.Read("zcode", Slot); return IsValid(key) ? key : null; }
    public static void Save(string key) { if (!IsValid(key)) throw new ArgumentException("密钥格式无效"); CredentialVault.Write("zcode", Slot, key); }
    public static void Delete() => CredentialVault.Delete("zcode", Slot);
    public static string Input(string? key) => JsonSerializer.Serialize(new { key = IsValid(key) ? key : null });
}
