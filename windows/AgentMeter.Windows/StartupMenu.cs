namespace AgentMeter.Windows;

internal sealed partial class MeterContext
{
    void ConfigureStartupMenu(ContextMenuStrip menu)
    {
        var item = new ToolStripMenuItem("登录 Windows 时启动") { Enabled = false };
        menu.Items.Add(item);
        StartupRegistration? startup = null;
        try
        {
            startup = new StartupRegistration(new WindowsStartupStore(), Environment.ProcessPath ?? "");
            item.Checked = startup.Enabled(); item.Enabled = true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or System.Security.SecurityException)
        { item.ToolTipText = "启动项不可用，请检查 Windows 启动应用设置"; }
        item.Click += (_, _) => {
            try { startup!.Set(!item.Checked); item.Checked = startup.Enabled(); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or System.Security.SecurityException)
            { window.ShowNotice("无法修改启动项，请检查 Windows 启动应用设置"); }
        };
    }
    internal void SyntheticBackgroundSmoke()
    {
        if (window.Visible || !tray.Visible || window.CurrentSnapshot is null)
            throw new InvalidOperationException("后台启动应显示托盘并保持面板收起");
    }
}
