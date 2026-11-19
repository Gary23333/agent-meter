using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>DeepSeek 的单个 API 密钥只存放在当前用户的 Windows 凭据管理器中。</summary>
internal static class DeepSeekKeyStore
{
    static readonly Guid Slot = new("75483e58-3afa-49de-ae55-90e5039f76e9");

    public static bool IsValid(string? key) => key is { Length: > 0 and <= 1280 } && key.All(c => c is >= '!' and <= '~');
    public static string? Read()
    {
        string? key = CredentialVault.Read("deepseek", Slot);
        return IsValid(key) ? key : null;
    }
    public static void Save(string key)
    {
        if (!IsValid(key)) throw new ArgumentException("密钥为空、过长或包含空白字符");
        CredentialVault.Write("deepseek", Slot, key);
    }
    public static void Delete() => CredentialVault.Delete("deepseek", Slot);
    public static string Input(string? key) => JsonSerializer.Serialize(new { key = IsValid(key) ? key : null });
}
