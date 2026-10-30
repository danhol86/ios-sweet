<#
.SYNOPSIS
    Install/launch iOS Sweet using Docker Desktop only (experimental QEMU TCG).
.DESCRIPTION
    Mounts the user's private kernel, device tree and iOS disk read-only.
    Stores selected Windows paths in ignored docker/local-config/windows.json,
    and leaves all persistent guest writes in a separate QCOW2 Docker state
    folder. Does not install a standalone WSL distribution.
.EXAMPLE
    .\tools\Start-IosSweet-Docker.ps1 -KernelPath D:\..\kernel.development.sweet -GuestDisk D:\..\ios.raw -StateDirectory D:\..\state
#>
[CmdletBinding()]
param(
    [string]$KernelPath = '',
    [string]$GuestDisk = '',
    [string]$DeviceTree = '',
    [string]$StateDirectory = '',
    [ValidateRange(1024,65535)][int]$Port = 8108,
    [ValidateRange(1,8)][int]$Cpus = 4,
    [ValidateRange(60,7200)][int]$Seconds = 7200,
    [switch]$Network,
    [switch]$TraceNetworkPath,
    [switch]$CheckOnly,
    [switch]$Interactive,
    [switch]$NoShortcut,
    [switch]$NoBrowser,
    [switch]$Stop
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compose=Join-Path $repo 'docker\compose.yml'
$settingsFile=Join-Path $repo 'docker\local-config\windows.json'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install/start Docker Desktop before using the Docker backend.' }
$dockerOS=(& docker info --format '{{.OSType}}' 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is not responding.' }
if ($dockerOS.Trim() -ne 'linux') { throw 'Docker Desktop must be in Linux containers mode.' }
& docker compose version --short | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
$project='ios-sweet-qemu'
if ($Stop) {
    & docker compose --env-file (Join-Path $repo 'docker\.env.example') -p $project -f $compose down
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop iOS Sweet Docker container.' }
    return
}
function Choose-File([string]$title) {
    Add-Type -AssemblyName System.Windows.Forms
    $d=New-Object System.Windows.Forms.OpenFileDialog
    $d.Title=$title
    $d.CheckFileExists=$true
    if ($d.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'A required file was not selected.' }
    return $d.FileName
}
$saved=$null
if (Test-Path -LiteralPath $settingsFile -PathType Leaf) {
    try { $saved=Get-Content -LiteralPath $settingsFile -Raw | ConvertFrom-Json }
    catch { throw "Invalid local Docker configuration: $settingsFile" }
}
function Select-Asset([string]$supplied, [string]$previous, [string]$default, [string]$title) {
    $path=if($supplied){$supplied}elseif($previous){$previous}else{$default}
    if (-not $path -or -not(Test-Path -LiteralPath $path -PathType Leaf)) {
        if ($Interactive -and -not $CheckOnly) { $path=Choose-File $title }
        else { throw "Missing $title. Specify its path or run Install-iOS-Sweet.cmd to choose it." }
    }
    return (Resolve-Path -LiteralPath $path).Path
}
$defaultKernel=Join-Path $repo 'xnu\out-qemu-0086\kernel.development.sweet'
$defaultGuest=Join-Path $repo 'docker\local-guest\ios16-net-test.raw'
$defaultAdt=Join-Path $repo 'research\ipsw-x\d22ap.adt'
$KernelPath=Select-Asset $KernelPath $saved.KernelPath $defaultKernel 'rebuilt SWEET XNU kernel.development.sweet'
$GuestDisk=Select-Asset $GuestDisk $saved.GuestDisk $defaultGuest 'your prepared iOS HFSX .raw guest image'
$DeviceTree=Select-Asset $DeviceTree $saved.DeviceTree $defaultAdt 'extracted iPhone X d22ap.adt device tree'
if ((Get-Item -LiteralPath $DeviceTree).Length -lt 16384) { throw 'Incomplete private D22AP device tree.' }
if ((Get-Item -LiteralPath $KernelPath).Length -lt 1000000) { throw 'Incomplete rebuilt XNU kernel.' }
if ((Get-Item -LiteralPath $GuestDisk).Length -lt 1GB) { throw 'Guest disk is unexpectedly small.' }
$KernelPath=(Resolve-Path -LiteralPath $KernelPath).Path
$GuestDisk=(Resolve-Path -LiteralPath $GuestDisk).Path
if (-not $StateDirectory) {
    if ($saved -and $saved.StateDirectory) { $StateDirectory=[string]$saved.StateDirectory }
    else { $StateDirectory=Join-Path $repo 'docker\local-state' }
}
if ($KernelPath -notmatch '^[A-Za-z]:\\' -or $GuestDisk -notmatch '^[A-Za-z]:\\') { throw 'Kernel and guest disk must be on a local Windows drive shared with Docker.' }
if ($DeviceTree -notmatch '^[A-Za-z]:\\') { throw 'Device tree must be on a local Windows drive shared with Docker.' }
if (-not (Test-Path -LiteralPath $StateDirectory)) {
    if ($CheckOnly) {
        $candidate=[IO.Path]::GetFullPath($StateDirectory)
        if ($candidate -notmatch '^[A-Za-z]:\\' -or -not (Test-Path -LiteralPath ([IO.Path]::GetPathRoot($candidate)))) {
            throw "State directory is not on an available local drive: $StateDirectory"
        }
        Write-Host "Check only: deployment will create state directory $candidate."
        $StateDirectory=$candidate
    } else {
        $null=New-Item -ItemType Directory -Path $StateDirectory -Force
    }
}
if (Test-Path -LiteralPath $StateDirectory) {
    $StateDirectory=(Resolve-Path -LiteralPath $StateDirectory).Path
}
if ($StateDirectory -notmatch '^[A-Za-z]:\\') { throw 'State directory must be on a local Windows drive.' }
$env:IOS_SWEET_KERNEL=$KernelPath.Replace([char]92,[char]47)
$env:IOS_SWEET_DISK=$GuestDisk.Replace([char]92,[char]47)
$env:IOS_SWEET_ADT=$DeviceTree.Replace([char]92,[char]47)
$env:IOS_SWEET_STATE_DIR=$StateDirectory.Replace([char]92,[char]47)
$env:IOS_SWEET_VIEWER_PORT=[string]$Port
$env:IOS_SWEET_CPUS=[string]$Cpus
$env:IOS_SWEET_SECONDS=[string]$Seconds
$env:IOS_SWEET_NETWORK=if($Network){'1'}else{'0'}
$env:IOS_SWEET_NECP_TRACE=if($Network -and $TraceNetworkPath){'1'}else{'0'}
& docker compose -p $project -f $compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration rejected.' }
Write-Host 'Docker Compose configuration validated; private kernel/guest will be mounted read-only.'
if ($CheckOnly) {
    Write-Host 'Check only. No Docker guest was started.'
    return
}
if ($Network) { Write-Warning 'Experimental network support is not yet verified in iOS Safari.' }
& docker compose -p $project -f $compose up --detach --build
if ($LASTEXITCODE -ne 0) { throw 'Docker QEMU launch failed.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $settingsFile))) {
    $null=New-Item -ItemType Directory -Path (Split-Path -Parent $settingsFile) -Force
}
$settings=[ordered]@{
    KernelPath=$KernelPath
    GuestDisk=$GuestDisk
    DeviceTree=$DeviceTree
    StateDirectory=$StateDirectory
}
$settings | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding UTF8
Write-Host "Viewer: http://127.0.0.1:$Port/"
Write-Host 'Stop: .\tools\Start-IosSweet-Docker.ps1 -Stop'
if (-not $NoShortcut) {
    $desktop=[Environment]::GetFolderPath('Desktop')
    $shortcut=Join-Path $desktop 'iOS Sweet (Docker).lnk'
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut($shortcut)
    $link.TargetPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $args='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'"'
    $args+=' -KernelPath "'+$KernelPath+'" -GuestDisk "'+$GuestDisk+'" -DeviceTree "'+$DeviceTree+'" -StateDirectory "'+$StateDirectory+'"'
    $args+=' -Port '+$Port+' -Cpus '+$Cpus+' -Seconds '+$Seconds
    if ($Network) { $args+=' -Network' }
    if ($TraceNetworkPath) { $args+=' -TraceNetworkPath' }
    $args+=' -Interactive'
    $link.Arguments=$args
    $link.WorkingDirectory=$repo
    $link.Description='Open interactive iOS Sweet in local Docker QEMU'
    $link.Save()
    Write-Host "One-click Docker launcher: $shortcut"
}
if (-not $NoBrowser -and $Interactive) {
    $url="http://127.0.0.1:$Port/"
    for ($i=0; $i -lt 90; $i++) {
        try {
            $response=Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { Start-Process $url; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
}
