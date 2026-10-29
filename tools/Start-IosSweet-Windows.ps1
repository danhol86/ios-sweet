<#
.SYNOPSIS
    Start experimental iOS-SWEET in WSL2/QEMU and open its Windows viewer.
.EXAMPLE
    .\Start-IosSweet-Windows.ps1 -Cpus 4 -KernelBuild 0084

This is an experimental boot interface, NOT a functional iPhone simulator.
#>
[CmdletBinding()]
param(
    [ValidateRange(1,8)][int]$Cpus = 4,
    [ValidateRange(30,7200)][int]$Seconds = 1200,
    [ValidateRange(1024,65535)][int]$Port = 8099,
    [ValidatePattern('^[0-9]{4}$')][string]$KernelBuild = '0084',
    [switch]$Ephemeral
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$wslPathResult = & wsl.exe -d Ubuntu-24.04 -- wslpath -a -u $repo
if ($LASTEXITCODE -ne 0 -or -not $wslPathResult) {
    throw 'WSL2 Ubuntu-24.04 is unavailable or cannot translate the repository path.'
}
$wslRepo = ($wslPathResult | Select-Object -First 1).Trim()
$kernel = "$wslRepo/xnu/out-qemu-$KernelBuild/kernel.development.sweet"
& wsl.exe -d Ubuntu-24.04 -- test -f $kernel
if ($LASTEXITCODE -ne 0) {
    throw "Missing kernel $kernel. Build or download a verified kernel first."
}

$url = "http://127.0.0.1:$Port/"
Write-Host "Booting experimental iOS-SWEET on $Cpus virtual CPUs..."
Write-Host "Live Windows framebuffer: $url"
Write-Host 'Keep this PowerShell window open; press Ctrl+C to end the experiment.'

$browserJob = Start-Job -ArgumentList $url -ScriptBlock {
    param($address)
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $address -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                Start-Process $address
                break
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
}
try {
    $ephemeralValue = if ($Ephemeral) { '1' } else { '0' }
    $wslArguments = @(
        '-d', 'Ubuntu-24.04', '--', 'env',
        "SWEET_QEMU_KERNEL=$kernel",
        "SWEET_QEMU_CPUS=$Cpus", "SWEET_QEMU_SECONDS=$Seconds",
        "SWEET_QEMU_PORT=$Port", "SWEET_QEMU_EPHEMERAL=$ephemeralValue",
        'bash', "$wslRepo/tools/start-qemu-desktop.sh"
    )
    & wsl.exe @wslArguments
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "QEMU returned exit code $LASTEXITCODE. Inspect the saved WSL log folder."
    }
} finally {
    Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
    Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
}
