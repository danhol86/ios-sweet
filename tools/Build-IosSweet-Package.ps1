<#
.SYNOPSIS
    Build a portable iOS Sweet source and installer ZIP from committed Git files.
.DESCRIPTION
    Excludes all untracked files by using git archive. Does not package Apple
    firmware, prepared guest disks, device-tree extracts, local kernels or keys.
.EXAMPLE
    .\tools\Build-IosSweet-Package.ps1 -Destination 'D:\Releases\ios-sweet.zip'
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()][string]$Destination = '',
    [switch]$CheckOnly
)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$head=(& git -C $repo rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[a-f0-9]{40}$') { throw 'A committed Git HEAD is required.' }
if (-not $Destination) { $Destination=Join-Path $repo ("ios-sweet-portable-"+$head.Substring(0,8)+'.zip') }
$Destination=[IO.Path]::GetFullPath($Destination)
if ([IO.Path]::GetExtension($Destination) -ne '.zip') { throw 'Destination must be a .zip archive.' }
if (Test-Path -LiteralPath $Destination) { throw "Destination already exists: $Destination" }
$names=@(& git -C $repo ls-tree -r --name-only HEAD)
if ($LASTEXITCODE -ne 0) { throw 'Unable to list tracked files.' }
$required=@('Install-iOS-Sweet.cmd','Start-iOS-Sweet-Docker.cmd','docker/compose.yml',
  'docker/Dockerfile','docker/entrypoint.sh','docs/ONE_CLICK_DEPLOY.md',
  'tools/mkadt.py','tools/Start-IosSweet-Docker.ps1')
foreach($name in $required){if($name -notin $names){throw "Missing tracked package component $name"}}
$bad=@($names | Where-Object {$_ -match '(?i)(^Users/|^research/ipsw-x/|(^|/)(local-state|local-guest|local-config|local-assets)/|\.((qcow2|raw|vhdx|im4p|adt|p8|p12|ipa|mobileprovision))$)'})
if($bad.Count){throw ('Private media paths found in tracked Git tree: '+($bad -join ', '))}
Write-Host "Portable package source: Git $head ($($names.Count) files)"
if($CheckOnly){Write-Host 'Check only: Git tree includes all installers and no private media extensions.';return}
$parent=Split-Path -Parent $Destination
if(-not(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
& git -C $repo archive --format=zip --output=$Destination HEAD
if($LASTEXITCODE -ne 0 -or -not(Test-Path -LiteralPath $Destination)){throw 'Git archive failed'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($Destination)
try{
  $entries=@($zip.Entries | Where-Object {$_.Name})
  if($entries.Count -ne $names.Count){throw "Archive file count mismatch: $($entries.Count)/$($names.Count)"}
  foreach($entry in $entries){if($entry.FullName -notin $names){throw "Unexpected entry: $($entry.FullName)"}}
}finally{$zip.Dispose()}
$hash=(Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest=$Destination+'.sha256'
[IO.File]::WriteAllText($manifest,$hash+'  '+[IO.Path]::GetFileName($Destination)+"`n",[Text.UTF8Encoding]::new($false))
Write-Host "Verified source-only ZIP: $Destination"
Write-Host "SHA256 $hash"
Write-Host 'Private prepared iOS guest disk, device tree and kernel must be added by the end user.'
