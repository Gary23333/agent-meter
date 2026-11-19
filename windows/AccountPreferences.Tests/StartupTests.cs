using AgentMeter.Windows;

internal static class StartupTests
{
    sealed class FakeStore : IStartupStore
    {
        public string? Value;
        public int Writes, Deletes;
        public string? Read() => Value;
        public void Write(string value) { Value = value; Writes++; }
        public void Delete() { Value = null; Deletes++; }
    }
    public static void Run()
    {
        var store = new FakeStore();
        string path = Path.Combine(Path.GetTempPath(), "含空格的目录", "AgentMeter.Windows.exe");
        var startup = new StartupRegistration(store, path);
        if (startup.Enabled()) throw new InvalidOperationException("首次启动不应自动启用开机启动");
        startup.Set(true);
        if (!startup.Enabled() || store.Value != "\"" + path + "\" --background" || store.Writes != 1) throw new InvalidOperationException("启动命令或路径引用错误");
        startup.Set(true);
        if (store.Writes != 1) throw new InvalidOperationException("相同配置不应反复写入");
        startup.Set(false);
        if (startup.Enabled() || store.Deletes != 1) throw new InvalidOperationException("启动项关闭失败");
        store.Value = "\"C:\\Other\\program.exe\"";
        try { startup.Set(true); throw new InvalidOperationException("不可覆盖其他启动配置"); }
        catch (InvalidDataException) { }
        if (store.Writes != 1 || store.Value != "\"C:\\Other\\program.exe\"") throw new InvalidOperationException("外部启动项不应修改");
        try { _ = new StartupRegistration(store, Path.Combine(Path.GetTempPath(), "other.exe")); throw new InvalidOperationException("不可设置非本应用启动"); }
        catch (InvalidDataException) { }
        if (Environment.GetEnvironmentVariable("AGENT_METER_TEST_STARTUP_REGISTRY") == "1")
        {
            string testPath = @"Software\AgentMeterSyntheticTests\" + Guid.NewGuid().ToString("N");
            try
            {
                var registry = new StartupRegistration(new WindowsStartupStore(testPath), path);
                if (registry.Enabled()) throw new InvalidOperationException("隔离启动项初始状态错误");
                registry.Set(true);
                if (!registry.Enabled()) throw new InvalidOperationException("隔离注册表写入失败");
                registry.Set(false);
                if (registry.Enabled()) throw new InvalidOperationException("隔离注册表删除失败");
            }
            finally { Microsoft.Win32.Registry.CurrentUser.DeleteSubKey(testPath, throwOnMissingSubKey: false); }
        }
        Console.WriteLine("登录启动选项隔离检查通过");
    }
}
