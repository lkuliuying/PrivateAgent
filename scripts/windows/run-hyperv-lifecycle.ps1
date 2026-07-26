[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$VMName,
    [Parameter(Mandatory = $true)] [string]$CheckpointName,
    [Parameter(Mandatory = $true)] [PSCredential]$Credential,
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
    [Parameter(Mandatory = $true)] [string]$ResultPath,
    [Parameter(Mandatory = $true)] [switch]$ConfirmRestore,
    [ValidateRange(60, 1800)] [int]$ReadyTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $ConfirmRestore) {
    throw '-ConfirmRestore is required because the selected VM checkpoint will replace all current guest state.'
}
if (-not (Get-Command Get-VM -ErrorAction SilentlyContinue)) {
    throw 'Hyper-V PowerShell module is unavailable.'
}

$old = (Resolve-Path -LiteralPath $OldInstaller).Path
$new = (Resolve-Path -LiteralPath $NewInstaller).Path
& (Join-Path $PSScriptRoot 'verify-updater-signatures.ps1') -Installer @($old, $new) -UpdaterPublicKeyFile $UpdaterPublicKeyFile
$lifecycleScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'install-lifecycle.ps1')).Path
$vm = Get-VM -Name $VMName -ErrorAction Stop
$checkpoints = @(Get-VMSnapshot -VMName $VMName | Where-Object { $_.Name -eq $CheckpointName })
if ($checkpoints.Count -ne 1) {
    throw "Expected exactly one checkpoint named '$CheckpointName' for VM '$VMName'."
}

if ($vm.State -ne 'Off') {
    Stop-VM -Name $VMName -TurnOff -Force
}
Restore-VMSnapshot -VMName $VMName -Name $CheckpointName -Confirm:$false
Start-VM -Name $VMName | Out-Null

$session = $null
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
do {
    try {
        $session = New-PSSession -VMName $VMName -Credential $Credential -ErrorAction Stop
    } catch {
        Start-Sleep -Seconds 2
    }
} while (-not $session -and [DateTimeOffset]::UtcNow -lt $deadline)
if (-not $session) {
    throw "PowerShell Direct did not become ready within $ReadyTimeoutSeconds seconds."
}

$guestRoot = "C:\PA-Lifecycle\$([Guid]::NewGuid().ToString('N'))"
$guestResult = "$guestRoot\result.json"
try {
    Invoke-Command -Session $session -ScriptBlock { param($Path) $null = New-Item -ItemType Directory -Path $Path -Force } -ArgumentList $guestRoot
    Copy-Item -LiteralPath $old -Destination "$guestRoot\old.exe" -ToSession $session
    Copy-Item -LiteralPath $new -Destination "$guestRoot\new.exe" -ToSession $session
    Copy-Item -LiteralPath $lifecycleScript -Destination "$guestRoot\install-lifecycle.ps1" -ToSession $session

    $guestExitCode = Invoke-Command -Session $session -ScriptBlock {
        param($Root, $OldVersion, $NewVersion, $EvidenceClass, $UpdaterScope, $IsProduction)
        $arguments = @(
            '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "$Root\install-lifecycle.ps1",
            '-OldInstaller', "$Root\old.exe", '-NewInstaller', "$Root\new.exe",
            '-ExpectedOldVersion', $OldVersion, '-ExpectedNewVersion', $NewVersion,
            '-ResultPath', "$Root\result.json", '-RequireAuthenticode',
            '-IdentityClass', $EvidenceClass,
            '-UpdaterVerificationScope', $UpdaterScope,
            '-UpdaterSignatureVerified'
        )
        if ($IsProduction) { $arguments += '-ProductionIdentity' }
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Wait -PassThru
        return $process.ExitCode
    } -ArgumentList $guestRoot, $ExpectedOldVersion, $ExpectedNewVersion, $IdentityClass, $UpdaterVerificationScope, ([bool]$ProductionIdentity)

    $resultDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($ResultPath))
    if ($resultDirectory) { $null = New-Item -ItemType Directory -Path $resultDirectory -Force }
    Copy-Item -FromSession $session -LiteralPath $guestResult -Destination $ResultPath
    Write-Host "[hyper-v] lifecycle result: $ResultPath"
    if ([int]$guestExitCode -ne 0) {
        throw "Hyper-V lifecycle failed with exit code $guestExitCode."
    }
} finally {
    if ($session) { Remove-PSSession $session }
}
