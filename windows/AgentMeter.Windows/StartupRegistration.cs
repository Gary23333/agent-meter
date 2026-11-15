using Microsoft.Win32;

namespace AgentMeter.Windows;

internal interface IStartupStore
{
    string? Read();
    void Write(string value);
    void Delete();
}

/// <summary>仅管理当前用户登录启动项；发现其他程序配置时保持原样。</summary>
internal sealed class WindowsStartupStore(string? keyPath = null) : IStartupStore
{
    readonly string path = keyPath ?? @"Software\Microsoft\Windows\CurrentVersion\Run";
    const string Entry = "AgentMeter.Windows";
    public string? Read()
    {
        using var key = Registry.CurrentUser.OpenSubKey(path, writable: false);
        object? value = key?.GetValue(Entry, null, RegistryValueOptions.DoNotExpandEnvironmentNames);
        return value is null ? null : value as string ?? throw new InvalidDataException("启动项格式无法识别");
    }
    public void Write(string value)
    {
        using var key = Registry.CurrentUser.CreateSubKey(path, writable: true) ?? throw new IOException("无法打开启动项");
        key.SetValue(Entry, value, RegistryValueKind.String);
    }
    public void Delete()
    {
        using var key = Registry.CurrentUser.OpenSubKey(path, writable: true);
        key?.DeleteValue(Entry, throwOnMissingValue: false);
    }
}

internal sealed class StartupRegistration(IStartupStore store, string executable)
{
    readonly string command = Quote(executable);
    static string Quote(string executable)
    {
        string path = Path.GetFullPath(executable);
        if (!Path.GetFileName(path).Equals("AgentMeter.Windows.exe", StringComparison.OrdinalIgnoreCase) || path.IndexOfAny(['"', '\r', '\n']) >= 0)
            throw new InvalidDataException("当前程序路径不适合用于开机启动");
        return "\"" + path + "\" --background";
    }
    public bool Enabled()
    {
        string? current = store.Read();
        if (current is null) return false;
        if (!string.Equals(current, command, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("发现其他启动配置，请手动检查 Windows 启动应用");
        return true;
    }
    public void Set(bool enabled)
    {
        bool current = Enabled();
        if (enabled == current) return;
        if (enabled) store.Write(command); else store.Delete();
    }
}
