namespace AgentMeter.Windows;

internal sealed partial class MeterContext
{
    void ConfigureStartupMenu(ContextMenuStrip menu)
    {
        var item = new ToolStripMenuItem("登录时启动（需系统允许）") { Enabled = false,
            ToolTipText = "注册启动项后，仍受 Windows 启动应用设置控制" };
        menu.Items.Add(item);
        StartupRegistration? startup = null;
        try
        {
            startup = new StartupRegistration(new WindowsStartupStore(), Environment.ProcessPath ?? "");
            item.Checked = startup.Enabled(); item.Enabled = true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or System.Security.SecurityException)
        { item.Text = "登录启动（配置不可用）"; item.ToolTipText = "启动项无法读取或不属于当前程序路径"; }
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
