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
    # Four vCPUs reproduced a kernel ticket-spinlock timeout between CPU 1
    # and CPU 3 after about an hour (2026-10-30). Default to stable UP mode.
    [ValidateRange(1,8)][int]$Cpus = 1,
    [ValidateRange(60,7200)][int]$Seconds = 7200,
    [switch]$Network,
    [switch]$NoNetwork,
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
if($Network -and $NoNetwork) { throw 'Choose -Network or -NoNetwork, not both.' }
$networkEnabled=(-not $NoNetwork)
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
$defaultKernel=if($networkEnabled){
    Join-Path $repo 'xnu\out-qemu-network-0099\kernel.development.sweet'
}else{
    Join-Path $repo 'xnu\out-qemu-0086\kernel.development.sweet'
}
$defaultGuest=Join-Path $repo 'docker\local-guest\ios16-net-test.raw'
$defaultAdt=Join-Path $repo 'research\ipsw-x\d22ap.adt'
$savedKernel=if($saved){[string]$saved.KernelPath}else{''}
if($networkEnabled -and $savedKernel -eq (Join-Path $repo 'xnu\out-qemu-0086\kernel.development.sweet')){
    # Migrate earlier GUI-only installs automatically; do not silently boot
    # a kernel that lacks networking with the new one-click installer.
    $savedKernel=''
}
$KernelPath=Select-Asset $KernelPath $savedKernel $defaultKernel 'network-enabled SWEET XNU kernel.development.sweet'
$GuestDisk=Select-Asset $GuestDisk $saved.GuestDisk $defaultGuest 'your prepared iOS HFSX .raw guest image'
$DeviceTree=Select-Asset $DeviceTree $saved.DeviceTree $defaultAdt 'extracted iPhone X d22ap.adt device tree'
if ((Get-Item -LiteralPath $DeviceTree).Length -lt 16384) { throw 'Incomplete private D22AP device tree.' }
if ((Get-Item -LiteralPath $KernelPath).Length -lt 1000000) { throw 'Incomplete rebuilt XNU kernel.' }
if ((Get-Item -LiteralPath $GuestDisk).Length -lt 1GB) { throw 'Guest disk is unexpectedly small.' }
$KernelPath=(Resolve-Path -LiteralPath $KernelPath).Path
$GuestDisk=(Resolve-Path -LiteralPath $GuestDisk).Path
if (-not $StateDirectory) {
    $oldState=Join-Path $repo 'docker\local-state'
    if ($saved -and $saved.StateDirectory -and [string]$saved.StateDirectory -ne $oldState) {
        $StateDirectory=[string]$saved.StateDirectory
    }else{
        # Never reopen an old GUI-only overlay or mutate experimental disks.
        $StateDirectory=Join-Path $repo 'docker\local-state\oneclick'
    }
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
$env:IOS_SWEET_NETWORK=if($networkEnabled){'1'}else{'0'}
$env:IOS_SWEET_NECP_TRACE=if($networkEnabled -and $TraceNetworkPath){'1'}else{'0'}
if($networkEnabled -and -not(Test-Path -LiteralPath (Join-Path $repo 'docker\network\iossweet-net-seed') -PathType Leaf)){
    throw 'iOS networking helper is missing from the installer. Extract the complete ZIP again.'
}
& docker compose -p $project -f $compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration rejected.' }
Write-Host 'Docker Compose configuration validated; private kernel/guest will be mounted read-only.'
if ($CheckOnly) {
    Write-Host 'Check only. No Docker guest was started.'
    return
}
$running=@(& docker compose -p $project -f $compose ps --status running -q ios-sweet)
if($LASTEXITCODE -ne 0){throw 'Cannot inspect running iOS Sweet containers.'}
if($running.Count -eq 0){
    $os=Get-CimInstance Win32_OperatingSystem
    if($os -and $os.FreePhysicalMemory -lt 3145728){
        throw 'At least 3 GiB of available Windows RAM is required to start the emulator safely.'
    }
    & docker compose -p $project -f $compose build ios-sweet
    if($LASTEXITCODE -ne 0){throw 'Docker QEMU image build failed.'}
    if($networkEnabled){
        Write-Host 'Preparing private iOS network configuration (first run only)...'
        & docker compose -p $project -f $compose run --no-deps --rm --entrypoint /usr/local/bin/iossweet-prepare-network ios-sweet
        if($LASTEXITCODE -ne 0){throw 'Could not prepare the private iOS network overlay. No guest was launched.'}
    }
    & docker compose -p $project -f $compose up --detach --no-build
    if($LASTEXITCODE -ne 0){throw 'Docker QEMU launch failed.'}
}else{
    Write-Host 'iOS Sweet is already running; reusing the existing guest.'
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $settingsFile))) {
    $null=New-Item -ItemType Directory -Path (Split-Path -Parent $settingsFile) -Force
}
$settings=[ordered]@{
    KernelPath=$KernelPath
    GuestDisk=$GuestDisk
    DeviceTree=$DeviceTree
    StateDirectory=$StateDirectory
    Network=$networkEnabled
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
    if (-not $networkEnabled) { $args+=' -NoNetwork' }
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
