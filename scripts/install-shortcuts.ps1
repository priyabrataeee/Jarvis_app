# Creates "Jarvis" shortcuts on the Desktop and in the Start menu.
# Run again any time to recreate them:  powershell -ExecutionPolicy Bypass -File scripts\install-shortcuts.ps1
#   -Startup      also start Jarvis automatically when you log in (adds it to the Startup folder)
#   -NoStartup    stop starting Jarvis at login (removes it from the Startup folder)

param([switch]$Startup, [switch]$NoStartup)

$appDir = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $appDir ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $appDir "jarvis_app.pyw"
$icon = Join-Path $appDir "jarvis.ico"

foreach ($path in @($pythonw, $launcher, $icon)) {
    if (-not (Test-Path $path)) { Write-Error "Missing: $path"; exit 1 }
}

$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) "Jarvis.lnk"
if ($NoStartup) {
    if (Test-Path $startupLink) { Remove-Item $startupLink; Write-Output "Removed $startupLink" }
    else { Write-Output "Jarvis was not set to start at login." }
    exit 0
}

$locations = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)
if ($Startup) { $locations += [Environment]::GetFolderPath("Startup") }

$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $locations) {
    $shortcut = $shell.CreateShortcut((Join-Path $folder "Jarvis.lnk"))
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$launcher`""
    $shortcut.WorkingDirectory = $appDir
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = "Jarvis voice assistant"
    $shortcut.Save()
    Write-Output "Created $(Join-Path $folder 'Jarvis.lnk')"
}
