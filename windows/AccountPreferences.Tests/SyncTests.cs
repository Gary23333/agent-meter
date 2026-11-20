using AgentMeter.Windows;

internal static class SyncTests
{
    public static void Run(string directory)
    {
        string syncDirectory = Path.Combine(directory, "sync");
        if (!SyncPreferences.ValidBaseUrl("https://sync.example.com")) throw new InvalidOperationException("https 地址应有效");
        if (!SyncPreferences.ValidBaseUrl("http://127.0.0.1:8899")) throw new InvalidOperationException("本机 http 地址应有效");
        if (!SyncPreferences.ValidBaseUrl("http://localhost:8899")) throw new InvalidOperationException("localhost 应有效");
        foreach (string value in new[] { "http://example.com", "ftp://127.0.0.1", "https://user:pass@example.com", "" })
            if (SyncPreferences.ValidBaseUrl(value)) throw new InvalidOperationException("不安全同步地址不应通过：" + value);

        string id = SyncPreferences.NewIdentifier();
        if (!SyncPreferences.IsIdentifier(id) || id.Length != 32) throw new InvalidOperationException("同步标识应为 32 位小写十六进制");
        if (SyncPreferences.IsIdentifier(id.ToUpperInvariant()) || SyncPreferences.IsIdentifier(new string('a', 31)))
            throw new InvalidOperationException("同步标识格式校验错误");

        var config = new SyncPreferences("https://sync.example.com", id, SyncPreferences.NewIdentifier(), 1795157000);
        config.Save(syncDirectory);
        var loaded = SyncPreferences.Load(syncDirectory);
        if (loaded != config) throw new InvalidOperationException("同步配置往返失败");
        File.WriteAllText(Path.Combine(syncDirectory, SyncPreferences.FileName), "not json");
        if (SyncPreferences.Load(syncDirectory) is not null) throw new InvalidOperationException("损坏同步配置不应被采用");
        SyncPreferences.Delete(syncDirectory);
        if (SyncPreferences.Load(syncDirectory) is not null) throw new InvalidOperationException("同步配置删除失败");

        const string run = """{"status":"ok","space_id":"0123456789abcdef0123456789abcdef","uploaded":true,"devices":2,"imported":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],"failed":[]}""";
        var result = SyncRunResult.Read(run);
        if (result is null || !result.Uploaded || result.Devices != 2 || result.Imported.Count != 1 || result.Failed.Count != 0)
            throw new InvalidOperationException("同步结果解析错误");
        if (SyncRunResult.Read("""{"status":"error","reason":"unauthorized"}""") is not null)
            throw new InvalidOperationException("错误结果不应被当作成功");

        const string devices = """{"status":"ok","devices":[{"device_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size":2048,"version":3,"updated_at":1795157000.5},{"device_id":"bad","size":1}]}""";
        var rows = SyncDeviceRow.Read(devices);
        if (rows.Count != 1 || rows[0].ShortId != "aaaaaaaa" || rows[0].SizeText != "2.0 KB" || rows[0].Version != 3)
            throw new InvalidOperationException("设备列表解析错误");
        if (rows[0].Updated == "—" || rows[0].Updated.Length != 16)
            throw new InvalidOperationException("设备更新时间应格式化为本地时间：" + rows[0].Updated);
        Console.WriteLine("多机同步设置与结果检查通过");
    }
}
