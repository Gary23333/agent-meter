using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace AgentMeter.Windows;

/// <summary>使用当前 Windows 用户的凭据管理器保存单个来源的密钥。</summary>
internal static class CredentialVault
{
    const uint Generic = 1, PersistLocalMachine = 2;
    const int NotFound = 1168, MaxBytes = 2560;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Credential
    {
        public uint Flags, Type;
        [MarshalAs(UnmanagedType.LPWStr)] public string? TargetName;
        [MarshalAs(UnmanagedType.LPWStr)] public string? Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist, AttributeCount;
        public IntPtr Attributes;
        [MarshalAs(UnmanagedType.LPWStr)] public string? TargetAlias;
        [MarshalAs(UnmanagedType.LPWStr)] public string? UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool CredWrite(ref Credential credential, uint flags);
    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);
    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool CredDelete(string target, uint type, uint flags);
    [DllImport("advapi32.dll", EntryPoint = "CredFree")]
    static extern void CredFree(IntPtr credential);

    static string Target(string provider, Guid id)
    {
        if (provider is not ("minimax" or "deepseek" or "zcode" or "volcengine" or "test")) throw new ArgumentException("不支持的凭据来源", nameof(provider));
        if (id == Guid.Empty) throw new ArgumentException("凭据标识无效", nameof(id));
        return $"AgentMeter/{provider}/{id:N}";
    }

    public static void Write(string provider, Guid id, string secret) => WriteTarget(Target(provider, id), secret);

    public static string? Read(string provider, Guid id) => ReadTarget(Target(provider, id));

    public static void Delete(string provider, Guid id) => DeleteTarget(Target(provider, id));

    /// <summary>同步主密钥按空间保存，目标名由 32 位十六进制空间标识组成。</summary>
    public static void WriteTarget(string target, string secret)
    {
        if (string.IsNullOrEmpty(target) || target.Any(char.IsControl)) throw new ArgumentException("凭据目标无效", nameof(target));
        if (string.IsNullOrEmpty(secret) || secret.Any(char.IsControl)) throw new ArgumentException("密钥为空或包含控制字符", nameof(secret));
        byte[] bytes = Encoding.Unicode.GetBytes(secret);
        if (bytes.Length > MaxBytes) { CryptographicOperations.ZeroMemory(bytes); throw new ArgumentException("密钥过长", nameof(secret)); }
        GCHandle handle = default;
        try
        {
            handle = GCHandle.Alloc(bytes, GCHandleType.Pinned);
            var credential = new Credential { Type = Generic, TargetName = target, CredentialBlobSize = (uint)bytes.Length,
                CredentialBlob = handle.AddrOfPinnedObject(), Persist = PersistLocalMachine, UserName = "AgentMeter" };
            if (!CredWrite(ref credential, 0)) throw new Win32Exception(Marshal.GetLastWin32Error(), "无法保存到 Windows 凭据管理器");
        }
        finally
        {
            CryptographicOperations.ZeroMemory(bytes);
            if (handle.IsAllocated) handle.Free();
        }
    }

    public static string? ReadTarget(string target)
    {
        if (string.IsNullOrEmpty(target) || target.Any(char.IsControl)) throw new ArgumentException("凭据目标无效", nameof(target));
        if (!CredRead(target, Generic, 0, out var pointer))
        {
            int error = Marshal.GetLastWin32Error();
            if (error == NotFound) return null;
            throw new Win32Exception(error, "无法读取 Windows 凭据管理器");
        }
        byte[]? bytes = null;
        try
        {
            var credential = Marshal.PtrToStructure<Credential>(pointer);
            if (credential.CredentialBlobSize == 0 || credential.CredentialBlobSize > MaxBytes || credential.CredentialBlobSize % 2 != 0 || credential.CredentialBlob == IntPtr.Zero)
                throw new InvalidDataException("凭据数据无效");
            bytes = new byte[credential.CredentialBlobSize];
            Marshal.Copy(credential.CredentialBlob, bytes, 0, bytes.Length);
            return Encoding.Unicode.GetString(bytes);
        }
        finally
        {
            if (bytes is not null) CryptographicOperations.ZeroMemory(bytes);
            CredFree(pointer);
        }
    }

    public static void DeleteTarget(string target)
    {
        if (string.IsNullOrEmpty(target) || target.Any(char.IsControl)) throw new ArgumentException("凭据目标无效", nameof(target));
        if (!CredDelete(target, Generic, 0))
        {
            int error = Marshal.GetLastWin32Error();
            if (error != NotFound) throw new Win32Exception(error, "无法从 Windows 凭据管理器删除");
        }
    }
}
