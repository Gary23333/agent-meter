namespace AgentMeter.Windows;

/// <summary>再次启动时通知当前用户会话中的已有实例显示面板。</summary>
internal sealed class SingleInstanceSignal : IDisposable
{
    internal const string DefaultName = "Local\\AgentMeterWindows.Show";
    readonly EventWaitHandle signal;
    RegisteredWaitHandle? registration;
    public SingleInstanceSignal(string name) => signal = new EventWaitHandle(false, EventResetMode.AutoReset, name);
    public void Notify() => signal.Set();
    public void Listen(Action callback)
    {
        if (registration is not null) throw new InvalidOperationException("唤起信号已监听");
        registration = ThreadPool.RegisterWaitForSingleObject(signal, (_, timedOut) => { if (!timedOut) callback(); }, null, Timeout.Infinite, false);
    }
    public void Dispose() { registration?.Unregister(null); signal.Dispose(); }
}
