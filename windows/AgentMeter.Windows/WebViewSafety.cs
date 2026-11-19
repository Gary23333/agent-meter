using Microsoft.Win32;

namespace AgentMeter.Windows;

/// <summary>拒绝可能覆盖专用资料目录或暴露浏览器调试接口的系统设置。</summary>
internal static class WebViewSafety
{
    static readonly string[] Variables = ["WEBVIEW2_USER_DATA_FOLDER", "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER", "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER"];
    static readonly string[] PolicyKeys = ["UserDataFolder", "BrowserExecutableFolder", "AdditionalBrowserArguments"];

    public static bool ContainsOverride(IEnumerable<string?> values) => values.Any(value => !string.IsNullOrEmpty(value));
    public static bool IsIsolationFailure(Exception error) =>
        error is InvalidOperationException && error.Message.StartsWith("webview_", StringComparison.Ordinal) ||
        error is IOException && error.Message.StartsWith("profile_", StringComparison.Ordinal);

    public static void EnsureNoOverrides()
    {
        if (ContainsOverride(Variables.Select(Environment.GetEnvironmentVariable))) throw new InvalidOperationException("webview_override_configured");
        foreach (var hive in new[] { RegistryHive.LocalMachine, RegistryHive.CurrentUser })
            foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
                using (var root = RegistryKey.OpenBaseKey(hive, view))
                    foreach (string name in PolicyKeys)
                    {
                        using var key = root.OpenSubKey(@"SOFTWARE\Policies\Microsoft\Edge\WebView2\" + name);
                        if (key is not null && key.GetValueNames().Length > 0) throw new InvalidOperationException("webview_policy_override_configured");
                    }
    }

    public static bool SameDirectory(string expected, string actual)
    {
        try { return string.Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(expected)),
                                   Path.TrimEndingDirectorySeparator(Path.GetFullPath(actual)), StringComparison.OrdinalIgnoreCase); }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException) { return false; }
    }
}
