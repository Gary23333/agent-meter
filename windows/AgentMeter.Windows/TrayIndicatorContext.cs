using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterContext
{
    readonly System.Windows.Forms.Timer indicatorTimer = new() { Interval = 60000 };
    Icon? indicatorIcon;
    string indicatorKey = "brand", indicatorMode = "lowest";
    bool indicatorDemo;

    void InitializeTrayIndicator(ContextMenuStrip menu, bool demo)
    {
        indicatorDemo = demo;
        indicatorMode = demo ? "lowest" : TrayIndicatorPreferences.Load(AccountPreferences.DefaultDirectory);
        var options = new ToolStripMenuItem("托盘余量");
        foreach (var (id, label) in TrayIndicator.Choices)
        {
            var item = new ToolStripMenuItem(label) { Checked = indicatorMode == id };
            item.Click += (_, _) => {
                try { if (!demo) TrayIndicatorPreferences.Save(AccountPreferences.DefaultDirectory, id); }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
                { window.ShowNotice("无法保存托盘显示设置"); return; }
                indicatorMode = id;
                foreach (ToolStripMenuItem other in options.DropDownItems) other.Checked = other == item;
                UpdateTrayIndicator();
            };
            options.DropDownItems.Add(item);
        }
        menu.Items.Insert(2, options);
        window.SnapshotUpdated += _ => UpdateTrayIndicator();
        // 面板收起时也检查快照时效；这里只重绘图标，不触发账户请求。
        indicatorTimer.Tick += (_, _) => UpdateTrayIndicator();
        indicatorTimer.Start(); UpdateTrayIndicator();
    }

    void UpdateTrayIndicator()
    {
        if (quitting) return;
        TrayIndicator display;
        try
        {
            using var snapshot = JsonDocument.Parse(window.CurrentSnapshot ?? "{}");
            display = TrayIndicator.Build(snapshot.RootElement, indicatorMode, DateTimeOffset.UtcNow, indicatorDemo);
        }
        catch (JsonException) { display = new(null, "Agent Meter · 账户快照暂不可用"); }
        tray.Text = display.Tooltip;
        if (display.IconKey == indicatorKey) return;
        Icon? next = null;
        try
        {
            if (display.Reading is not null) next = TrayIndicatorIcon.Create(display.Reading.Remaining);
            tray.Icon = next ?? icon;
            var previous = indicatorIcon;
            indicatorIcon = next; next = null; indicatorKey = display.IconKey;
            previous?.Dispose();
        }
        catch (Exception ex) when (ex is ArgumentException or System.ComponentModel.Win32Exception or System.Runtime.InteropServices.ExternalException)
        {
            tray.Icon = icon; indicatorIcon?.Dispose(); indicatorIcon = null; indicatorKey = "brand";
            window.ShowNotice("托盘数字暂时无法绘制，请打开面板查看");
        }
        finally { next?.Dispose(); }
    }

    internal void SyntheticTrayIndicatorSmoke()
    {
        if (!indicatorDemo || window.CurrentSnapshot is null) throw new InvalidOperationException("托盘检查需要完整演示快照");
        var menu = (ToolStripMenuItem)tray.ContextMenuStrip!.Items[2];
        using var document = JsonDocument.Parse(window.CurrentSnapshot);
        // 真实 NotifyIcon 的切换和克隆释放仅在隔离 Windows 构建机运行。
        for (int round = 0; round < 12; round++)
            for (int index = 0; index < TrayIndicator.Choices.Length; index++)
            {
                ((ToolStripMenuItem)menu.DropDownItems[index]).PerformClick();
                var expected = TrayIndicator.Build(document.RootElement, TrayIndicator.Choices[index].Id, DateTimeOffset.UtcNow, demo: true);
                if (indicatorKey != expected.IconKey || tray.Text != expected.Tooltip ||
                    menu.DropDownItems.OfType<ToolStripMenuItem>().Count(item => item.Checked) != 1 ||
                    (expected.Reading is null) != (indicatorIcon is null) || !tray.Visible)
                    throw new InvalidOperationException("托盘来源切换、图标生命周期或提示不正确");
                using var bitmap = tray.Icon!.ToBitmap();
            }
    }
}
