using System.Security.Cryptography;

namespace AgentMeter.Windows;

/// <summary>主密钥只存在 Windows 凭据管理器，空间标识是目标名的一部分。</summary>
internal static class SyncSecrets
{
    static string Target(string spaceId)
    {
        if (!SyncPreferences.IsIdentifier(spaceId)) throw new ArgumentException("同步空间标识无效", nameof(spaceId));
        return "AgentMeter/sync/" + spaceId;
    }

    public static void Save(string spaceId, byte[] masterKey)
    {
        if (masterKey.Length != 32) throw new ArgumentException("同步主密钥长度无效", nameof(masterKey));
        CredentialVault.WriteTarget(Target(spaceId), Convert.ToBase64String(masterKey));
    }

    public static byte[]? Read(string spaceId)
    {
        string? encoded = CredentialVault.ReadTarget(Target(spaceId));
        if (encoded is null) return null;
        try
        {
            byte[] value = Convert.FromBase64String(encoded);
            if (value.Length == 32) return value;
            CryptographicOperations.ZeroMemory(value);
            return null;
        }
        catch (FormatException) { return null; }
    }

    public static void Delete(string spaceId)
    {
        try { CredentialVault.DeleteTarget(Target(spaceId)); }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or ArgumentException) { }
    }

    public static string NewMasterKey()
    {
        byte[] value = RandomNumberGenerator.GetBytes(32);
        try { return Convert.ToBase64String(value); }
        finally { CryptographicOperations.ZeroMemory(value); }
    }
}
