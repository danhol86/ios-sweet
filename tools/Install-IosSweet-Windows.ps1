<#
.SYNOPSIS
    One-click setup for the experimental SWEET QEMU runner on Windows 11/WSL2.
.DESCRIPTION
    Requires a user-supplied, legally obtained iOS guest raw disk and a rebuilt
    SWEET XNU kernel. Apple firmware is neither downloaded nor redistributed.
    Installer is idempotent: it never overwrites an existing guest or overlay.
.EXAMPLE
    .\tools\Install-IosSweet-Windows.ps1 -Interactive
.EXAMPLE
    .\tools\Install-IosSweet-Windows.ps1 -Distro Ubuntu-24.04-D -KernelBuild 0086 -GuestDisk /home/ios-sweet-test/ios16-mgcall-test.raw -CheckOnly
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Distro = '',
    [ValidatePattern('^\d{4}$')][string]$KernelBuild = '0086',
    [string]$KernelFile = '',
    [string]$DeviceTree = '',
    [string]$GuestDisk = '',
    [string]$Overlay = '',
    [switch]$Network,
    [switch]$CheckOnly,
    [switch]$Interactive,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -notmatch '^[A-Za-z]:\\') { throw 'Move the project to a local Windows drive first.' }
$wslRepo = '/mnt/' + $repo.Substring(0,1).ToLowerInvariant() + '/' + $repo.Substring(3).Replace([char]92,[char]47)
function To-LinuxPath([string]$value) {
    if ($value.StartsWith('/')) { return $value }
    $p = (Resolve-Path -LiteralPath $value -ErrorAction Stop).Path
    if ($p -notmatch '^([A-Za-z]):\\(.*)$') { throw "Cannot convert network/UNC path: $p" }
    return '/mnt/' + $matches[1].ToLowerInvariant() + '/' + $matches[2].Replace([char]92,[char]47)
}
function Select-UserFile([string]$title) {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = $title
    $dlg.CheckFileExists = $true
    $dlg.Filter = 'All files (*.*)|*.*'
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'A required user-provided file was not selected.' }
    return $dlg.FileName
}
if (-not $Distro) {
    $available = ((& wsl.exe --list --quiet 2>&1 | Out-String) -replace "`0", '')
    $Distro = if ($available -match 'Ubuntu-24\.04-D') { 'Ubuntu-24.04-D' } else { 'Ubuntu-24.04' }
}
$kernelInRepo = Join-Path $repo "xnu\out-qemu-$KernelBuild\kernel.development.sweet"
if ($CheckOnly) {
    Write-Host "Checking $repo on WSL $Distro (no changes)..."
} else {
    & wsl.exe -d $Distro -- test -d /etc
    if ($LASTEXITCODE -ne 0) {
        if ($Distro -ne 'Ubuntu-24.04') { throw "Unknown distro '$Distro'; install it or select Ubuntu-24.04." }
        Write-Host 'Installing WSL2 Ubuntu 24.04. Windows may require administrator approval and a reboot.'
        & wsl.exe --install -d Ubuntu-24.04
        throw 'Complete any requested reboot and run the installer again.'
    }
    Write-Host 'Ensuring QEMU, LLVM, and Python are installed in WSL...'
    & wsl.exe -d $Distro -u root -- bash -lc 'set -e; if ! command -v qemu-system-aarch64 >/dev/null || ! command -v qemu-img >/dev/null || ! command -v llvm-nm >/dev/null || ! command -v python3 >/dev/null; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends qemu-system-arm qemu-utils llvm python3; fi'
    if ($LASTEXITCODE -ne 0) { throw 'WSL dependencies could not be installed.' }
}
if (-not (Test-Path -LiteralPath $kernelInRepo -PathType Leaf)) {
    if (-not $KernelFile -and $Interactive -and -not $CheckOnly) {
        $KernelFile = Select-UserFile 'Choose your rebuilt SWEET kernel.development.sweet (not proprietary iOS firmware)'
    }
    if ($KernelFile -and -not $CheckOnly) {
        $kernelSource = (Resolve-Path -LiteralPath $KernelFile).Path
        $dir = Split-Path -Parent $kernelInRepo
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        if (Test-Path -LiteralPath $kernelInRepo) { throw 'Refusing to overwrite an installed kernel.' }
        Copy-Item -LiteralPath $kernelSource -Destination $kernelInRepo -ErrorAction Stop
        Write-Host "Kernel copied into $kernelInRepo"
    }
}
$adtFile = Join-Path $repo 'research\ipsw-x\d22ap.adt'
if (-not (Test-Path -LiteralPath $adtFile -PathType Leaf)) {
    if (-not $DeviceTree -and $Interactive -and -not $CheckOnly) {
        $DeviceTree = Select-UserFile 'Select your extracted iPhone X DeviceTree d22ap.adt (from your own IPSW)'
    }
    if (-not $DeviceTree -or $CheckOnly) {
        throw "Missing private iPhone X device tree: $adtFile. Provide -DeviceTree with your extracted d22ap.adt."
    }
    $sourceTree = (Resolve-Path -LiteralPath $DeviceTree).Path
    $treeDir = Split-Path -Parent $adtFile
    if (-not (Test-Path -LiteralPath $treeDir)) { New-Item -ItemType Directory -Path $treeDir -Force | Out-Null }
    if (Test-Path -LiteralPath $adtFile) { throw 'Refusing to overwrite a device tree.' }
    Copy-Item -LiteralPath $sourceTree -Destination $adtFile -ErrorAction Stop
    Write-Host 'Private device tree copied locally and excluded from Git.'
}
if ((Get-Item -LiteralPath $adtFile).Length -lt 16384) { throw 'Device tree looks incomplete. Select an extracted d22ap.adt.' }
if (-not $GuestDisk -and $Interactive -and -not $CheckOnly) {
    $GuestDisk = Select-UserFile 'Choose your locally prepared iOS raw guest disk'
}
if (-not $GuestDisk) { $GuestDisk = '/home/ios-sweet-test/ios16-mgcall-test.raw' }
$linuxDisk = To-LinuxPath $GuestDisk
if (-not $Overlay) { $Overlay = '/home/ios-sweet-test/ios-sweet-deploy-overlay.qcow2' }
if (-not $Overlay.StartsWith('/')) { throw 'Overlay must be a Linux absolute path inside the selected WSL distribution.' }
if ($linuxDisk -eq $Overlay) { throw 'Disk and overlay paths must be different.' }
$linuxKernel = "$wslRepo/xnu/out-qemu-$KernelBuild/kernel.development.sweet"
& wsl.exe -d $Distro -- test -f $linuxKernel
if ($LASTEXITCODE -ne 0) { throw "Missing rebuilt SWEET kernel: $kernelInRepo. Provide -KernelFile; not included in Git." }
& wsl.exe -d $Distro -- test -f $linuxDisk
if ($LASTEXITCODE -ne 0) { throw "Missing iOS guest disk: $linuxDisk. Provide -GuestDisk; iOS firmware is not bundled." }
& wsl.exe -d $Distro -- bash -c 'command -v qemu-system-aarch64 >/dev/null && command -v llvm-nm >/dev/null && command -v qemu-img >/dev/null && command -v python3 >/dev/null'
if ($LASTEXITCODE -ne 0) { throw 'Missing WSL tools. Rerun without -CheckOnly to install dependencies.' }
Write-Host "Ready: $Distro / kernel $KernelBuild / guest $linuxDisk / overlay $Overlay"
if ($CheckOnly) { Write-Host 'Check only: no files or shortcuts changed.'; return }
$launcher = Join-Path $repo 'tools\Start-IosSweet-Windows.ps1'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Windows launcher not present.' }
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '" -Distro ' + $Distro + ' -KernelBuild ' + $KernelBuild + ' -Disk "' + $linuxDisk + '" -Overlay "' + $Overlay + '"'
if ($Network) { $arguments += ' -Network'; Write-Warning 'Guest internet is experimental and NOT yet verified.' }
if (-not $NoShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $path = Join-Path $desktop 'iOS Sweet (QEMU).lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = $arguments
    $link.WorkingDirectory = $repo
    $link.Description = 'Launch the experimental iOS SWEET guest from WSL2'
    $link.Save()
    Write-Host "Created one-click launcher: $path"
}
Write-Host 'Setup complete. Open the iOS Sweet (QEMU) shortcut to launch the viewer.'
