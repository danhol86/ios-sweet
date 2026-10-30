<#
.SYNOPSIS
    One-click Windows Docker Desktop prerequisite bootstrap.
.DESCRIPTION
    Uses the trusted Docker.DockerDesktop winget package if Docker Desktop
    is absent. Does not install any separate Ubuntu distro. May need Windows
    UAC elevation and a reboot if Docker Desktop/WSL components are missing.
#>
[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
if(-not $IsWindows -and $PSVersionTable.PSEdition -ne 'Desktop'){
    throw 'This bootstrap is only for Windows.'
}
$desktop='C:\Program Files\Docker\Docker\Docker Desktop.exe'
$cliDir='C:\Program Files\Docker\Docker\resources\bin'
if(-not(Get-Command docker -ErrorAction SilentlyContinue) -and (Test-Path $cliDir)){
    $env:PATH=$cliDir+';'+$env:PATH
}
if(-not(Test-Path -LiteralPath $desktop -PathType Leaf)){
    if($CheckOnly){
        Write-Output 'Docker Desktop is not installed. Normal first run can use winget.'
        return
    }
    if(-not(Get-Command winget -ErrorAction SilentlyContinue)){
        throw 'Docker Desktop is missing and Windows Package Manager (winget) is unavailable. Install Docker Desktop from docker.com.'
    }
    Write-Host 'Installing official Docker Desktop through Windows Package Manager. Windows might ask for elevation.'
    & winget install --id Docker.DockerDesktop --exact --source winget --accept-source-agreements --accept-package-agreements --silent
    if($LASTEXITCODE -ne 0){
        throw 'Docker Desktop setup did not complete. If Windows requests a reboot, reboot and run the same installer again.'
    }
    if(-not(Test-Path -LiteralPath $desktop -PathType Leaf)){
        throw 'Docker Desktop was installed but needs Windows to be restarted before the installer can continue.'
    }
    $env:PATH=$cliDir+';'+$env:PATH
}
if(-not(Get-Command docker -ErrorAction SilentlyContinue)){
    throw 'Docker Desktop executable exists but the Docker CLI was not found.'
}
try {
    $os=(& docker info --format '{{.OSType}}' 2>$null)
} catch { $os='' }
if($os -eq 'linux'){
    Write-Host 'Docker Desktop (Linux containers) is ready.'
    return
}
if($CheckOnly){
    Write-Output 'Docker Desktop is installed but its daemon is not currently ready.'
    return
}
Write-Host 'Starting Docker Desktop; a first-time installation may require Windows setup confirmation.'
if(-not(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)){
    Start-Process -FilePath $desktop
}
for($attempt=0;$attempt -lt 90;$attempt++){
    Start-Sleep -Seconds 2
    try{$os=(& docker info --format '{{.OSType}}' 2>$null)}catch{$os=''}
    if($os -eq 'linux'){
        Write-Host 'Docker Desktop Linux backend is ready.'
        return
    }
    if($os -eq 'windows'){
        throw 'Docker Desktop is using Windows containers. Switch it to Linux containers and retry.'
    }
}
throw 'Docker Desktop Linux backend did not become ready. Check Docker Desktop setup, reboot if requested, then run this installer again.'
