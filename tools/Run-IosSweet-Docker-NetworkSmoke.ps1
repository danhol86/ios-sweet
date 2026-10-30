# Isolated Docker-only QEMU network diagnostic. Never use the stable overlay.
[CmdletBinding()]
param(
    [string]$KernelPath,
    [string]$GuestDisk,
    [string]$DeviceTree,
    [string]$SourceProjectRoot,
    [string]$StateDirectory,
    [ValidatePattern('^[a-z0-9][a-z0-9-]{2,35}$')]
    [string]$RunName='ios-sweet-net-smoke',
    [ValidateRange(1024,65535)]
    [int]$Port=8111,
    [switch]$CheckOnly,
    [switch]$Stop
)
$ErrorActionPreference='Stop'
if (-not(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop not found.' }
if ((& docker info --format '{{.OSType}}' 2>$null).Trim() -ne 'linux') {
    throw 'Docker Linux containers backend unavailable.'
}
if ($Stop) {
    if ($RunName -notin @(& docker ps -a --format '{{.Names}}')) {
        Write-Host "No diagnostic container named $RunName"; return
    }
    & docker stop --timeout 20 $RunName
    if ($LASTEXITCODE -ne 0) { throw "Cannot stop $RunName" }
    & docker rm $RunName
    if ($LASTEXITCODE -ne 0) { throw "Cannot remove $RunName" }
    Write-Host "Stopped only $RunName; guest overlay and captures remain on disk."
    return
}
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $SourceProjectRoot) { $SourceProjectRoot=Join-Path (Split-Path -Parent $repo) 'ios-sweet' }
$SourceProjectRoot=(Resolve-Path -LiteralPath $SourceProjectRoot).Path
if (-not(Test-Path -LiteralPath (Join-Path $SourceProjectRoot 'tools\qemu-sweet.py'))) {
    throw 'Source project does not contain QEMU tools.'
}
if (-not $KernelPath) {
    $dirs=@(Get-ChildItem (Join-Path $repo 'xnu') -Directory |
        Where-Object {$_.Name -match '^out-qemu-'} | Sort-Object Name -Descending)
    foreach($d in $dirs) {
        $candidate=Join-Path $d.FullName 'kernel.development.sweet'
        if (Test-Path -LiteralPath $candidate) { $KernelPath=$candidate; break }
    }
}
if (-not $GuestDisk) { $GuestDisk=Join-Path $SourceProjectRoot 'docker\local-guest\ios16-net-test.raw' }
if (-not $DeviceTree) { $DeviceTree=Join-Path $SourceProjectRoot 'research\ipsw-x\d22ap.adt' }
if (-not $StateDirectory) { $StateDirectory=Join-Path $SourceProjectRoot "docker\local-state\$RunName" }
foreach($item in @(@($KernelPath,1000000),@($GuestDisk,1GB),@($DeviceTree,16384))) {
    if (-not(Test-Path -LiteralPath $item[0] -PathType Leaf)) { throw "Missing input: $($item[0])" }
    if ((Get-Item -LiteralPath $item[0]).Length -lt $item[1]) { throw "Incomplete input: $($item[0])" }
}
$KernelPath=(Resolve-Path -LiteralPath $KernelPath).Path
$GuestDisk=(Resolve-Path -LiteralPath $GuestDisk).Path
$DeviceTree=(Resolve-Path -LiteralPath $DeviceTree).Path
$StateDirectory=[IO.Path]::GetFullPath($StateDirectory)
foreach($path in @($KernelPath,$GuestDisk,$DeviceTree,$StateDirectory)) {
    if ($path -notmatch '^[A-Za-z]:\\') { throw "Path not on a local Windows drive: $path" }
}
if ($RunName -in @(& docker ps -a --format '{{.Names}}')) {
    throw "Diagnostic container $RunName already exists. Stop it first."
}
if (Test-Path -LiteralPath (Join-Path $StateDirectory 'ios.qcow2')) {
    throw 'Refusing to reuse existing guest overlay. Select a new RunName.'
}
Write-Host "Kernel: $KernelPath"
Write-Host "Docker network diagnostic viewer: http://127.0.0.1:$Port/"
Write-Host "Isolated state: $StateDirectory"
if ($CheckOnly) { Write-Host 'CHECK_ONLY_PASS: no Docker changes'; return }
$null=New-Item -ItemType Directory -Path $StateDirectory -Force
function DockerPath([string]$p) { return $p.Replace([char]92,[char]47) }
$argsList=@(
    'run','--detach','--init','--name',$RunName,
    '--publish',('127.0.0.1:'+$Port+':8099'),
    '--env','SWEET_QEMU_KERNEL=/guest/kernel.development.sweet',
    '--env','SWEET_QEMU_DISK=/guest/ios.raw',
    '--env','SWEET_QEMU_PRODUCT_ADT=/guest/d22ap.adt',
    '--env','SWEET_QEMU_OVERLAY=/state/ios.qcow2',
    '--env','SWEET_QEMU_OUTPUT_BASE=/state',
    '--env','SWEET_QEMU_PORT=8099',
    # The stable Docker guest panicked in SMP ticket spinlock with 4 CPUs.
    '--env','SWEET_QEMU_CPUS=1',
    '--env','SWEET_QEMU_SECONDS=1800',
    '--env','SWEET_QEMU_NETWORK=1',
    '--env','SWEET_QEMU_NECP_TRACE=1',
    '--env','SWEET_QEMU_LOG_FLAGS=guest_errors,unimp',
    '--env','SWEET_QEMU_SAMPLE=MobileSafari,com.apple.WebKit,networkd,configd,mDNSResponder',
    '--env','SWEET_QEMU_SAMPLE_DELAY=90',
    '--env','SWEET_QEMU_SAMPLE_INTERVAL=20',
    '--volume',((DockerPath $SourceProjectRoot)+':/app:ro'),
    '--volume',((DockerPath $KernelPath)+':/guest/kernel.development.sweet:ro'),
    '--volume',((DockerPath $GuestDisk)+':/guest/ios.raw:ro'),
    '--volume',((DockerPath $DeviceTree)+':/guest/d22ap.adt:ro'),
    '--volume',((DockerPath $StateDirectory)+':/state'),
    'ios-sweet-qemu:local'
)
& docker @argsList
if ($LASTEXITCODE -ne 0) { throw 'Isolated Docker networking test failed to start.' }
Write-Host "Running $RunName. Stop with -Stop -RunName $RunName."
