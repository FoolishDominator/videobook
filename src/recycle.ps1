# JSON on stdin keeps literal file paths out of executable shell strings.
# https://learn.microsoft.com/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Version -lt [Version]'6.2') { throw 'Recycling requires Windows 8 or later' }
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($request.root).TrimEnd('\') + '\'
$paths = @($request.paths | ForEach-Object {
    $path = [IO.Path]::GetFullPath($_)
    if (-not $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside cleanup root: $path"
    }
    $item = Get-Item -LiteralPath $path -Force
    $ancestor = $item
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked path: $path" }
        $ancestor = if ($ancestor.PSIsContainer) { $ancestor.Parent } else { $ancestor.Directory }
    }
    if ($item.PSIsContainer) {
        $links = @(Get-ChildItem -LiteralPath $path -Force -Recurse -Attributes ReparsePoint)
        if ($links.Count) { throw "Linked subtree: $path" }
    }
    $item.FullName
})
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

[ComImport, Guid("947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IFileOperation {
    void Advise(IntPtr sink, out uint cookie);
    void Unadvise(uint cookie);
    void SetOperationFlags(uint flags);
    void SetProgressMessage([MarshalAs(UnmanagedType.LPWStr)] string message);
    void SetProgressDialog(IntPtr dialog);
    void SetProperties(IntPtr properties);
    void SetOwnerWindow(IntPtr window);
    void ApplyPropertiesToItem(IntPtr item);
    void ApplyPropertiesToItems(IntPtr items);
    void RenameItem(IntPtr item, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
    void RenameItems(IntPtr items, [MarshalAs(UnmanagedType.LPWStr)] string name);
    void MoveItem(IntPtr item, IntPtr destination, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
    void MoveItems(IntPtr items, IntPtr destination);
    void CopyItem(IntPtr item, IntPtr destination, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
    void CopyItems(IntPtr items, IntPtr destination);
    void DeleteItem(IntPtr item, IntPtr sink);
    void DeleteItems(IntPtr items);
    void NewItem(IntPtr destination, uint attributes, [MarshalAs(UnmanagedType.LPWStr)] string name,
                 [MarshalAs(UnmanagedType.LPWStr)] string template, IntPtr sink);
    void PerformOperations();
    void GetAnyOperationsAborted([MarshalAs(UnmanagedType.Bool)] out bool aborted);
}

public static class VideoBookRecycle {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int SHCreateItemFromParsingName(string path, IntPtr context, ref Guid iid, out IntPtr item);

    public static void Send(string[] paths) {
        var type = Type.GetTypeFromCLSID(new Guid("3AD05575-8857-4850-9277-11B85BDB8E09"));
        var operation = (IFileOperation)Activator.CreateInstance(type);
        var items = new List<IntPtr>();
        try {
            // RECYCLEONDELETE, ADDUNDORECORD, EARLYFAILURE, NOERRORUI,
            // WANTNUKEWARNING, NO_CONNECTED_ELEMENTS, NOCONFIRMATION, SILENT.
            // Operate only on the listed paths and never retry a permanent delete.
            operation.SetOperationFlags(0x00080000 | 0x20000000 | 0x00100000 | 0x0400 | 0x4000 | 0x2000 | 0x0010 | 0x0004);
            var iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE");
            foreach (string path in paths) {
                IntPtr item;
                Marshal.ThrowExceptionForHR(SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out item));
                items.Add(item);
                operation.DeleteItem(item, IntPtr.Zero);
            }
            operation.PerformOperations();
            bool aborted;
            operation.GetAnyOperationsAborted(out aborted);
            if (aborted) throw new InvalidOperationException("Recycle operation was aborted; retain remaining files");
        } finally {
            foreach (IntPtr item in items) Marshal.Release(item);
            Marshal.FinalReleaseComObject(operation);
        }
    }
}
'@
if ($paths.Count) { [VideoBookRecycle]::Send([string[]]$paths) }
foreach ($path in $paths) {
    if (Test-Path -LiteralPath $path) { throw "Recycle failed: $path" }
}
