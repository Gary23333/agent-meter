namespace AgentMeter.Windows;

/// <summary>设置菜单与弹层使用相同配色，保留 Windows 菜单的键盘导航和勾选行为。</summary>
internal static class TrayMenuStyle
{
    public static void Apply(ContextMenuStrip menu, VisualTheme theme)
    {
        menu.Renderer = new ToolStripProfessionalRenderer(new Palette(theme));
        menu.BackColor = theme.Card; menu.ForeColor = theme.Primary;
        void Visit(ToolStripItemCollection items)
        {
            foreach (ToolStripItem item in items)
            {
                item.ForeColor = theme.Primary;
                if (item is ToolStripMenuItem branch)
                {
                    branch.DropDown.BackColor = theme.Card; branch.DropDown.ForeColor = theme.Primary;
                    Visit(branch.DropDownItems);
                }
            }
        }
        Visit(menu.Items);
    }
    sealed class Palette(VisualTheme theme) : ProfessionalColorTable
    {
        public override Color ToolStripDropDownBackground => theme.Card;
        public override Color MenuBorder => theme.Border;
        public override Color MenuItemBorder => theme.Border;
        public override Color MenuItemSelected => theme.Border;
        public override Color MenuItemSelectedGradientBegin => theme.Border;
        public override Color MenuItemSelectedGradientEnd => theme.Border;
        public override Color MenuItemPressedGradientBegin => theme.Border;
        public override Color MenuItemPressedGradientMiddle => theme.Border;
        public override Color MenuItemPressedGradientEnd => theme.Border;
        public override Color ImageMarginGradientBegin => theme.Card;
        public override Color ImageMarginGradientMiddle => theme.Card;
        public override Color ImageMarginGradientEnd => theme.Card;
        public override Color CheckBackground => theme.Selected;
        public override Color CheckSelectedBackground => theme.Selected;
        public override Color CheckPressedBackground => theme.Selected;
        public override Color SeparatorDark => theme.Border;
        public override Color SeparatorLight => theme.Card;
    }
}
