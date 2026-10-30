<#
.SYNOPSIS
    Build/launch iOS Sweet in Docker Desktop (experimental QEMU TCG; no KVM).
.DESCRIPTION
    Mounts user's private kernel and iOS disk read-only. State is isolated in
    a Windows directory. Publishes viewer only on 127.0.0.1.
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
    [switch]$CheckOnly,
    [switch]$Interactive,
    [switch]$NoShortcut,
    [switch]$NoBrowser,
    [switch]$Stop
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compose=Join-Path $repo 'docker\compose.yml'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install/start Docker Desktop before using the Docker backend.' }
& docker info --format '{{.OSType}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is not responding.' }
$project='ios-sweet-qemu'
if ($Stop) {
    & docker compose -p $project -f $compose down
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
if (-not $KernelPath) {
    $KernelPath=Join-Path $repo 'xnu\out-qemu-0086\kernel.development.sweet'
    if (-not (Test-Path -LiteralPath $KernelPath) -and $Interactive) { $KernelPath=Choose-File 'Choose a rebuilt SWEET XNU kernel' }
}
if (-not $GuestDisk -and $Interactive) { $GuestDisk=Choose-File 'Choose your locally prepared raw iOS guest disk' }
if (-not $GuestDisk) { throw 'Specify -GuestDisk. Apple iOS firmware is not provided.' }
$adtFile = Join-Path $repo 'research\ipsw-x\d22ap.adt'
if (-not (Test-Path -LiteralPath $adtFile -PathType Leaf)) {
    if (-not $DeviceTree -and $Interactive -and -not $CheckOnly) { $DeviceTree = Choose-File 'Choose your extracted iPhone X device tree d22ap.adt' }
    if (-not $DeviceTree -or $CheckOnly) { throw "Missing private device tree $adtFile. Supply -DeviceTree." }
    $from = (Resolve-Path -LiteralPath $DeviceTree).Path
    $adtParent = Split-Path -Parent $adtFile
    if (-not (Test-Path -LiteralPath $adtParent)) { New-Item -ItemType Directory -Path $adtParent -Force | Out-Null }
    Copy-Item -LiteralPath $from -Destination $adtFile -ErrorAction Stop
}
if ((Get-Item -LiteralPath $adtFile).Length -lt 16384) { throw 'Incomplete device tree file.' }
$KernelPath=(Resolve-Path -LiteralPath $KernelPath).Path
$GuestDisk=(Resolve-Path -LiteralPath $GuestDisk).Path
if (-not $StateDirectory) { $StateDirectory=Join-Path $repo 'docker\local-state' }
if ($KernelPath -notmatch '^[A-Za-z]:\\' -or $GuestDisk -notmatch '^[A-Za-z]:\\') { throw 'Kernel and guest disk must be on a local Windows drive shared with Docker.' }
if (-not (Test-Path -LiteralPath $StateDirectory)) {
    if ($CheckOnly) { throw "State directory missing: $StateDirectory (create it for deployment)" }
    $null=New-Item -ItemType Directory -Path $StateDirectory -Force
}
$StateDirectory=(Resolve-Path -LiteralPath $StateDirectory).Path
if ($StateDirectory -notmatch '^[A-Za-z]:\\') { throw 'State directory must be on a local Windows drive.' }
$env:IOS_SWEET_KERNEL=$KernelPath.Replace([char]92,[char]47)
$env:IOS_SWEET_DISK=$GuestDisk.Replace([char]92,[char]47)
$env:IOS_SWEET_STATE_DIR=$StateDirectory.Replace([char]92,[char]47)
$env:IOS_SWEET_VIEWER_PORT=[string]$Port
$env:IOS_SWEET_CPUS=[string]$Cpus
$env:IOS_SWEET_SECONDS=[string]$Seconds
$env:IOS_SWEET_NETWORK=if($Network){'1'}else{'0'}
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
Write-Host "Viewer: http://127.0.0.1:$Port/"
Write-Host 'Stop: .\tools\Start-IosSweet-Docker.ps1 -Stop'
if (-not $NoShortcut) {
    $desktop=[Environment]::GetFolderPath('Desktop')
    $shortcut=Join-Path $desktop 'iOS Sweet (Docker).lnk'
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut($shortcut)
    $link.TargetPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $args='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'"'
    $args+=' -KernelPath "'+$KernelPath+'" -GuestDisk "'+$GuestDisk+'" -StateDirectory "'+$StateDirectory+'"'
    $args+=' -Port '+$Port+' -Cpus '+$Cpus+' -Seconds '+$Seconds
    if ($Network) { $args+=' -Network' }
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
