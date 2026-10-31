<#
.SYNOPSIS
  Read-only smoke test of the running native Windows iOS Sweet emulator.
.DESCRIPTION
  Verifies one QEMU instance, its executable, boot configuration and active
  kernel checksum, plus the loopback viewer and a valid PNG frame. It never
  starts or stops a guest, accesses a remote website, or modifies any QCOW2.
  A rendered frame proves that QMP works; it does not prove Safari works.
#>
[CmdletBinding()]
param(
  [ValidateSet(1,2)][int]$ExpectedCpus=2,
  [string]$ExpectedKernelSha256='',
  [switch]$SaveScreenshot
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$state=Join-Path $repo 'windows-runtime\state\active-native.json'
if(-not(Test-Path -LiteralPath $state)){throw 'No running native iOS Sweet state file'}
$active=Get-Content -LiteralPath $state -Raw|ConvertFrom-Json
if([int]$active.cpus -ne $ExpectedCpus){throw 'Unexpected guest CPU count'}
if(-not $active.kernel_sha256){throw 'Active guest kernel identity was not recorded'}
$actualHash=([string]$active.kernel_sha256).ToLowerInvariant()
if($actualHash -notmatch '^[0-9a-f]{64}$'){throw 'Invalid saved kernel hash'}
if($ExpectedKernelSha256 -and $actualHash -ne $ExpectedKernelSha256.ToLowerInvariant()){
  throw 'Active kernel hash is not the requested kernel'
}
$legacy='85039335d05d335d1f9b33f7c8131d274477c50020915ff0335b42428abe998a'
$quiet='7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8'
if($actualHash -eq $quiet){
  $kernel=Join-Path $repo 'windows-runtime\guest\kernel.aks-quiet.sweet'
}elseif($actualHash -eq $legacy){
  $kernel=Join-Path $repo 'windows-runtime\guest\kernel.development.sweet'
}else{throw 'Unknown native kernel; cannot verify against a local file'}
if(-not(Test-Path -LiteralPath $kernel)){throw 'Active kernel file is missing'}
if((Get-FileHash -LiteralPath $kernel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $actualHash){
  throw 'Installed kernel differs from recorded active kernel'
}
$procs=@(Get-CimInstance Win32_Process -Filter "Name='qemu-system-aarch64.exe'")
if($procs.Count -ne 1 -or $procs[0].ProcessId -ne [int]$active.qemu_pid){
  throw 'One verified native QEMU process was expected'
}
$exe=Join-Path $repo 'windows-runtime\qemu\qemu-system-aarch64.exe'
if(-not $procs[0].ExecutablePath -or
   -not [IO.Path]::GetFullPath($procs[0].ExecutablePath).Equals(
     [IO.Path]::GetFullPath($exe),[StringComparison]::OrdinalIgnoreCase)){
  throw 'Running QEMU executable is not this project installation'
}
if([int]$active.viewer_port -ne 8108 -or [int]$active.qmp_port -ne 4444){
  throw 'Unexpected viewer or QMP port; refusing to probe other services'
}
$info=Invoke-RestMethod -Uri 'http://127.0.0.1:8108/status.json' -TimeoutSec 8
if($info.mode -ne 'Native Windows QEMU' -or [int]$info.cores -ne $ExpectedCpus -or
   [bool]$info.diagnostics -ne [bool]$active.diagnostics){
  throw 'Viewer configuration differs from active guest state'
}
$run=[IO.Path]::GetFullPath([string]$active.run)
$stateRoot=[IO.Path]::GetFullPath((Join-Path $repo 'windows-runtime\state'))
if(-not $run.StartsWith(($stateRoot.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)){
  throw 'Active run folder is not under the expected state directory'
}
$frame=Join-Path $run 'native-smoke-frame.png'
if(Test-Path -LiteralPath $frame){throw 'Smoke-test frame already exists; refusing overwrite'}
try{
  $response=Invoke-WebRequest -Uri 'http://127.0.0.1:8108/frame.png' -UseBasicParsing -TimeoutSec 30 -OutFile $frame -PassThru
  if($response.StatusCode -ne 200){throw 'Viewer did not return a full PNG frame'}
  $bytes=[IO.File]::ReadAllBytes($frame)
  if($bytes.Length -lt 128 -or -not ([Convert]::ToBase64String($bytes[0..7]) -eq 'iVBORw0KGgo=')){
    throw 'Viewer snapshot is not a valid PNG signature'
  }
  Write-Output ('IOS_SWEET_SMOKE_PASS cores='+$ExpectedCpus+' qemu_pid='+$active.qemu_pid+
    ' kernel_sha256='+$actualHash+' frame_bytes='+$bytes.Length)
  Write-Output 'SAFARI_NETWORK_CHECK=not_tested_by_smoke_script'
}finally{
  if(-not $SaveScreenshot -and (Test-Path -LiteralPath $frame)){
    Remove-Item -LiteralPath $frame -Force
  }
}
