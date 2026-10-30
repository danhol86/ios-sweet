<#
.SYNOPSIS
  Start experimental native Windows QEMU instead of running QEMU in Docker.
.DESCRIPTION
  Uses installed Windows QEMU ARM64 (TCG software emulation, not WHPX).
  Requires a locally prepared iPhone X disk, the verified SWEET kernel and
  DeviceTree; it never downloads or redistributes Apple firmware.

  Refuses to start another guest alongside Docker or a native QEMU instance.
  Refuses launch while RAM is too low. Does not stop Docker automatically.
#>
[CmdletBinding()]
param(
  [switch]$CheckOnly,
  [switch]$Stop,
  [switch]$NoBrowser
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script=Join-Path $PSScriptRoot 'iossweet-native-windows.py'
$python=(Get-Command python.exe -ErrorAction Stop).Source
if($Stop) {
  & $python $script --stop
  if($LASTEXITCODE -ne 0){throw 'Could not gracefully stop native iOS guest.'}
  return
}
& $python $script --check
if($LASTEXITCODE -ne 0){throw 'Windows-native QEMU prerequisites failed.'}
if($CheckOnly){return}
$other=@(Get-CimInstance Win32_Process -Filter "Name='qemu-system-aarch64.exe'" -ErrorAction SilentlyContinue)
if($other.Count){throw 'A native QEMU instance is already running. Refusing another.'}
$docker=@(& docker ps --format '{{.Names}}' 2>$null |
  Where-Object{$_ -match '^ios-sweet-(qemu|netprobe)-'})
if($docker.Count){
  throw 'Docker iOS Sweet is still running. Stop that single guest with Start-IosSweet-Docker.ps1 -Stop before switching. The existing state will be preserved.'
}
$os=Get-CimInstance Win32_OperatingSystem
$available=[double]$os.FreePhysicalMemory/1MB
if($available -lt 8){
  throw ('Windows has only '+([math]::Round($available,1))+' GiB RAM free. The iOS VM needs 8 GiB. Free RAM before launching, to avoid extreme paging.')
}
$args='"'+$script+'"'
if($NoBrowser){$args+=' --no-browser'}
$process=Start-Process -FilePath $python -ArgumentList $args -PassThru -WindowStyle Hidden
Write-Host ('Started native Windows iOS Sweet process '+$process.Id)
Write-Host 'If successful, viewer: http://127.0.0.1:8108/'
Write-Host 'To stop without losing the overlay: powershell -File tools/Start-IosSweet-Windows.ps1 -Stop'
