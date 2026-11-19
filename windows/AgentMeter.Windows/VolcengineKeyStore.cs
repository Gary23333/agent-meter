using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record VolcengineKeys(string access_key_id, string secret_access_key);
/// <summary>AccessKey 对作为一个凭据原子写入，避免只保存其中一半。</summary>
internal static class VolcengineKeyStore
{
    static readonly Guid Slot = new("5f17d103-cbdb-40a6-a9f4-95136447d91e");
    public static bool Valid(VolcengineKeys? keys) => keys is not null && keys.access_key_id is { Length: >= 2 and <= 240 } &&
        keys.access_key_id.StartsWith("AK", StringComparison.Ordinal) && keys.secret_access_key is { Length: > 0 and <= 512 } &&
        (keys.access_key_id + keys.secret_access_key).All(c => c is >= '!' and <= '~') && JsonSerializer.Serialize(keys).Length <= 1280;
    public static VolcengineKeys? Read()
    {
        string? raw = CredentialVault.Read("volcengine", Slot);
        if (raw is null) return null;
        try { var keys = JsonSerializer.Deserialize<VolcengineKeys>(raw); return Valid(keys) ? keys : null; }
        catch (JsonException) { return null; }
    }
    public static void Save(VolcengineKeys keys)
    {
        if (!Valid(keys)) throw new ArgumentException("AccessKey 格式无效");
        CredentialVault.Write("volcengine", Slot, JsonSerializer.Serialize(keys));
    }
    public static void Delete() => CredentialVault.Delete("volcengine", Slot);
    public static string Input(VolcengineKeys? keys) => JsonSerializer.Serialize(new { credentials = Valid(keys) ? keys : null });
}
