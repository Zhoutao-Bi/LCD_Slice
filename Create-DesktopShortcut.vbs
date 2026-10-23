Option Explicit
Dim shell, files, root, target, link, dest, number
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
target = files.BuildPath(root, "LumaSlice.exe")
If Not files.FileExists(target) Then
    target = files.BuildPath(root, "dist\LumaSlice\LumaSlice.exe")
End If
If Not files.FileExists(target) Then
    MsgBox "Please extract the complete LumaSlice folder first.", 48, "LumaSlice"
    WScript.Quit 1
End If
dest = files.BuildPath(shell.SpecialFolders("Desktop"), "LumaSlice.lnk")
number = 1
Do While files.FileExists(dest)
    number = number + 1
    dest = files.BuildPath(shell.SpecialFolders("Desktop"), "LumaSlice (" & number & ").lnk")
Loop
Set link = shell.CreateShortcut(dest)
link.TargetPath = target
link.WorkingDirectory = files.GetParentFolderName(target)
link.IconLocation = target & ",0"
link.Description = "LumaSlice LCD PNG slicer"
link.Save
MsgBox "Desktop shortcut created.", 64, "LumaSlice"
