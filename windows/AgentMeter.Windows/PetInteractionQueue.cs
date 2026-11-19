namespace AgentMeter.Windows;

/// <summary>限制待播放动作数量；拥塞时先释放拖动状态，避免形象卡在半空。</summary>
internal sealed class PetInteractionQueue
{
    readonly Queue<string> pending = new();
    public void Add(string interaction)
    {
        if (interaction is not ("drag-start" or "drag-end" or "poke" or "refresh")) throw new ArgumentException("未知桌宠动作");
        if (pending.Count >= 16)
        {
            pending.Clear(); pending.Enqueue("drag-end");
            if (interaction == "drag-end") return;
        }
        pending.Enqueue(interaction);
    }
    public string? Take() => pending.Count > 0 ? pending.Dequeue() : null;
}
