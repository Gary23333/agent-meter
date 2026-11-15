using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddUsagePeriodSelector()
    {
        var strip = new NavigationStrip { Name = "usage-period-selector", Height = 40, Margin = new Padding(0, 2, 0, 12), BackColor = Card };
        var buttons = new List<NavigationTab>();
        foreach (var (id, label) in new[] { ("today", "今日"), ("7d", "7 天"), ("30d", "30 天"), ("all", "全部") })
        {
            var button = new NavigationTab { Name = "usage-period-" + id, Text = label, Font = tabRegular,
                AccessibleName = "本机用量：" + label };
            button.SetAppearance(theme, usagePeriod == id);
            button.Click += (_, _) => {
                if (usagePeriod == id || lastSnapshot is null) return;
                try { if (!demo) UsagePeriodPreferences.Save(AccountPreferences.DefaultDirectory, id); }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
                { status.Text = "无法保存用量周期设置"; return; }
                usagePeriod = id;
                using var snapshot = JsonDocument.Parse(lastSnapshot);
                Render(snapshot.RootElement); content.AutoScrollPosition = Point.Empty;
            };
            buttons.Add(button); strip.Controls.Add(button);
        }
        strip.Resize += (_, _) => {
            int width = Math.Max(1, (strip.ClientSize.Width - 6) / buttons.Count);
            for (int index = 0; index < buttons.Count; index++) buttons[index].Bounds = new Rectangle(3 + width * index, 3, width, 34);
        };
        content.Controls.Add(strip);
    }
}
