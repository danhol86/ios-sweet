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
  [switch]$SrgbDisplay,
  [switch]$Diagnostics,
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
if($other.Count){
  if($other.Count -eq 1 -and $other[0].ExecutablePath -and
      $other[0].ExecutablePath.StartsWith((Join-Path $repo 'windows-runtime\qemu'),[StringComparison]::OrdinalIgnoreCase)){
    if($SrgbDisplay){
      # Reopen an existing sRGB guest; never launch a second VM or silently
      # substitute a guest booted with different virtual display properties.
      $recordPath=Join-Path $repo 'windows-runtime\state\active-native.json'
      if(-not (Test-Path -LiteralPath $recordPath)){
        throw 'An iOS guest is running but its display mode cannot be verified. Refusing a duplicate.'
      }
      $record=Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
      if(([int]$record.qemu_pid -ne [int]$other[0].ProcessId) -or (-not $record.srgb_display)){
        throw 'The running guest does not match the requested sRGB mode. Stop it cleanly before changing display modes.'
      }
    }
    try {
      $response=Invoke-WebRequest -Uri 'http://127.0.0.1:8108/' -UseBasicParsing -TimeoutSec 3
      if($response.StatusCode -eq 200){
        Write-Host 'iOS Sweet is already running on Windows. Opening its existing viewer; no second instance.'
        if(-not $NoBrowser){Start-Process 'http://127.0.0.1:8108/'}
        return
      }
    }catch {}
  }
  throw 'A native QEMU instance is already running but its viewer is not verified. Refusing a duplicate.'
}
$docker=@()
if(Get-Command docker -ErrorAction SilentlyContinue){
  $docker=@(& docker ps --format '{{.Names}}' 2>$null |
    Where-Object{$_ -match '^ios-sweet-(qemu|netprobe)-'})
}
if($docker.Count){
  throw 'Docker iOS Sweet is still running. Stop that single guest with Start-IosSweet-Docker.ps1 -Stop before switching. The existing state will be preserved.'
}
$os=Get-CimInstance Win32_OperatingSystem
$available=[double]$os.FreePhysicalMemory/1MB
if($available -lt 6){
  throw ('Windows has only '+([math]::Round($available,1))+' GiB RAM free. The iOS VM needs at least 6 GiB free at startup. Free RAM before launching.')
}
$launchArgs='"'+$script+'"'
if($NoBrowser){$launchArgs+=' --no-browser'}
if($SrgbDisplay){$launchArgs+=' --srgb-display'}
if($Diagnostics){$launchArgs+=' --diagnostics'}
$logDir=Join-Path $repo 'windows-runtime\logs'
if(-not(Test-Path -LiteralPath $logDir)){New-Item -ItemType Directory -Path $logDir -Force|Out-Null}
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$outLog=Join-Path $logDir ('native-launch-'+$stamp+'.log')
$errLog=Join-Path $logDir ('native-launch-'+$stamp+'.err.log')
$process=Start-Process -FilePath $python -ArgumentList $launchArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Start-Sleep -Seconds 1
if($process.HasExited){
  $detail=(Get-Content -LiteralPath $errLog -Raw -ErrorAction SilentlyContinue)
  throw ('Native iOS Sweet exited before startup. '+$detail+' See '+$outLog)
}
Write-Host ('Started native Windows iOS Sweet process '+$process.Id)
Write-Host 'If successful, viewer: http://127.0.0.1:8108/'
Write-Host ('Startup log: '+$outLog)
Write-Host 'To stop without losing the overlay: powershell -File tools/Start-IosSweet-Windows.ps1 -Stop'
