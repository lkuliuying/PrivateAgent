[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$OldInstaller,
    [Parameter(Mandatory = $true)] [string]$NewInstaller,
    [Parameter(Mandatory = $true)] [string]$ExpectedOldVersion,
    [Parameter(Mandatory = $true)] [string]$ExpectedNewVersion,
    [Parameter(Mandatory = $true)] [string]$UpdaterPublicKeyFile,
    [ValidateSet('unclassified', 'self-signed-mechanism', 'trusted-ca-production')]
    [string]$IdentityClass = 'unclassified',
    [switch]$ProductionIdentity,
    [ValidateSet('unclassified', 'ephemeral-mechanism', 'embedded-production')]
    [string]$UpdaterVerificationScope = 'unclassified',
    [string]$ResultDirectory = (Join-Path $PWD 'dist\windows-sandbox-lifecycle'),
    [ValidateRange(60, 7200)] [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Escape-Xml([string]$Value) {
    return [Security.SecurityElement]::Escape($Value)
}
function Quote-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

$sandboxExe = Join-Path $env:WINDIR 'System32\WindowsSandbox.exe'
if (-not (Test-Path -LiteralPath $sandboxExe -PathType Leaf)) {
    throw 'Windows Sandbox is unavailable. Enable Containers-DisposableClientVM and reboot.'
}
$old = (Resolve-Path -LiteralPath $OldInstaller).Path
$new = (Resolve-Path -LiteralPath $NewInstaller).Path
& (Join-Path $PSScriptRoot 'verify-updater-signatures.ps1') -Installer @($old, $new) -UpdaterPublicKeyFile $UpdaterPublicKeyFile
$scriptsDirectory = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$resultRoot = [IO.Path]::GetFullPath($ResultDirectory)
$null = New-Item -ItemType Directory -Path $resultRoot -Force
$runId = [Guid]::NewGuid().ToString('N')
$resultName = "lifecycle-$runId.json"
$exitName = "lifecycle-$runId.exitcode"
$runnerPath = Join-Path $resultRoot "lifecycle-$runId.ps1"
$configPath = Join-Path $resultRoot "lifecycle-$runId.wsb"

$oldGuest = "C:\PA-Old\$([IO.Path]::GetFileName($old))"
$newGuest = "C:\PA-New\$([IO.Path]::GetFileName($new))"
$runner = @"
`$ErrorActionPreference = 'Continue'
`$arguments = @{
  OldInstaller = $(Quote-PowerShellLiteral $oldGuest)
  NewInstaller = $(Quote-PowerShellLiteral $newGuest)
  ExpectedOldVersion = $(Quote-PowerShellLiteral $ExpectedOldVersion)
  ExpectedNewVersion = $(Quote-PowerShellLiteral $ExpectedNewVersion)
  ResultPath = $(Quote-PowerShellLiteral "C:\PA-Results\$resultName")
  RequireAuthenticode = `$true
  IdentityClass = $(Quote-PowerShellLiteral $IdentityClass)
  UpdaterVerificationScope = $(Quote-PowerShellLiteral $UpdaterVerificationScope)
  UpdaterSignatureVerified = `$true
}
$(if ($ProductionIdentity) { '`$arguments.ProductionIdentity = `$true' } else { '' })
& 'C:\PA-Scripts\install-lifecycle.ps1' @arguments
`$code = `$LASTEXITCODE
[IO.File]::WriteAllText('C:\PA-Results\$exitName', [string]`$code)
shutdown.exe /s /t 0
exit `$code
"@
[IO.File]::WriteAllText($runnerPath, $runner, [Text.UTF8Encoding]::new($false))

$command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\PA-Results\$([IO.Path]::GetFileName($runnerPath))"
$config = @"
<Configuration>
  <Networking>Disable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <MappedFolders>
    <MappedFolder><HostFolder>$(Escape-Xml (Split-Path -Parent $old))</HostFolder><SandboxFolder>C:\PA-Old</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$(Escape-Xml (Split-Path -Parent $new))</HostFolder><SandboxFolder>C:\PA-New</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$(Escape-Xml $scriptsDirectory)</HostFolder><SandboxFolder>C:\PA-Scripts</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$(Escape-Xml $resultRoot)</HostFolder><SandboxFolder>C:\PA-Results</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>$(Escape-Xml $command)</Command></LogonCommand>
</Configuration>
"@
[IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))

$process = Start-Process -FilePath $sandboxExe -ArgumentList ('"{0}"' -f $configPath) -PassThru
if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    $process.Kill()
    throw "Windows Sandbox lifecycle timed out after $TimeoutSeconds seconds."
}
$exitPath = Join-Path $resultRoot $exitName
$resultPath = Join-Path $resultRoot $resultName
if (-not (Test-Path -LiteralPath $exitPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
    throw 'Windows Sandbox closed without producing lifecycle evidence.'
}
$guestExitCode = [int]([IO.File]::ReadAllText($exitPath).Trim())
Write-Host "[sandbox] lifecycle result: $resultPath"
if ($guestExitCode -ne 0) {
    throw "Windows Sandbox lifecycle failed with exit code $guestExitCode."
}
