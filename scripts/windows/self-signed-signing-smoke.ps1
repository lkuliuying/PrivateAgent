[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputExe,
    [Parameter(Mandatory = $true)]
    [string]$ResultPath,
    [ValidateRange(5, 600)]
    [int]$ExternalTimeoutSeconds = 180
)

# This validates only the signing machinery.  Its identity is deliberately
# named TEST ONLY and must never be used to classify an artifact as production.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$source = (Resolve-Path -LiteralPath $InputExe).Path
$ResultPath = [IO.Path]::GetFullPath($ResultPath)
$resultDirectory = Split-Path -Parent $ResultPath
if ($resultDirectory) { $null = New-Item -ItemType Directory -Path $resultDirectory -Force }
$stagePath = "$ResultPath.stage"
$runRoot = Join-Path $env:TEMP "private-agent-signing-smoke-$([Guid]::NewGuid().ToString('N'))"
$null = New-Item -ItemType Directory -Path $runRoot
$target = Join-Path $runRoot 'mechanism-test.exe'
$pfx = Join-Path $runRoot 'mechanism-test.pfx'
$cer = Join-Path $runRoot 'mechanism-test.cer'
$subject = 'CN=PrivateAgent LOCAL SELF-SIGNED TEST ONLY'
$thumbprint = $null
$importedThumbprints = @()
$password = [Guid]::NewGuid().ToString('N')
$stage = 'prepare'
$outcome = $null
$failureRecord = $null
$cleanupErrors = [System.Collections.Generic.List[string]]::new()

function Set-SmokeStage([string]$Value) {
    $script:stage = $Value
    [IO.File]::WriteAllText($stagePath, $Value, [Text.UTF8Encoding]::new($false))
}

function Invoke-ExternalWithTimeout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "[self-signed-smoke] $Description"
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $ArgumentList -join ' '
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "$Description could not be started." }
        if (-not $process.WaitForExit($ExternalTimeoutSeconds * 1000)) {
            try {
                $process.Kill()
            } catch {
                throw "$Description timed out and its exact process could not be terminated."
            }
            throw "$Description timed out after $ExternalTimeoutSeconds seconds."
        }
        $exitCode = [int]$process.ExitCode
        if ($exitCode -ne 0) {
            throw "$Description failed with exit code $exitCode."
        }
    } finally {
        $process.Dispose()
    }
}

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $matches = @($roots | ForEach-Object {
        Get-ChildItem -LiteralPath $_ -Filter signtool.exe -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq 'x64' }
    } | Sort-Object FullName -Descending)
    if ($matches.Count -eq 0) { throw 'signtool.exe was not found.' }
    return $matches[0].FullName
}

try {
    Set-SmokeStage 'copy-input'
    Copy-Item -LiteralPath $source -Destination $target
    Set-SmokeStage 'create-test-certificate'
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddDays(1) `
        -KeyExportPolicy Exportable
    $thumbprint = $certificate.Thumbprint
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force
    Set-SmokeStage 'export-test-certificate'
    Export-PfxCertificate -Cert $certificate -FilePath $pfx -Password $securePassword | Out-Null
    Export-Certificate -Cert $certificate -FilePath $cer | Out-Null
    Set-SmokeStage 'remove-temporary-private-certificate'
    Remove-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -Force

    Set-SmokeStage 'import-and-inspect-pfx'
    $env:PA_CODESIGN_PASSWORD = $password
    $importResult = & (Join-Path $PSScriptRoot 'codesign-certificate.ps1') -Action Import -PfxPath $pfx |
        ConvertFrom-Json
    $thumbprint = $importResult.thumbprint
    $importedThumbprints = @($importResult.imported_thumbprints)
    $inspection = & (Join-Path $PSScriptRoot 'codesign-certificate.ps1') `
        -Action Inspect -Thumbprint $thumbprint -ExpectedSubject $subject | ConvertFrom-Json

    $signTool = Find-SignTool
    Set-SmokeStage 'authenticode-sign-and-timestamp'
    Invoke-ExternalWithTimeout -FilePath $signTool -Description 'Authenticode signing and RFC3161 timestamping' `
        -ArgumentList @('sign', '/fd', 'SHA256', '/sha1', $thumbprint, '/tr',
            'http://timestamp.digicert.com', '/td', 'SHA256', '/d',
            '"PrivateAgent TEST ONLY"', "`"$target`"")
    Set-SmokeStage 'authenticode-mechanism-verify'
    $verification = & (Join-Path $PSScriptRoot 'verify-authenticode.ps1') `
        -Path $target -ExpectedThumbprint $thumbprint -RequireTimestamp `
        -AllowUntrustedSelfSigned | ConvertFrom-Json

    $outcome = [ordered]@{
        status = 'passed'
        production_identity = $false
        identity = 'self-signed mechanism test only'
        certificate_subject = $inspection.subject
        authenticode_status = $verification.status
        trust_verified = $verification.trust_verified
        verification_scope = $verification.verification_scope
        timestamped = $verification.timestamped
        tamper_detected = $verification.tamper_detected
        input_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        signed_copy_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    }
} catch {
    $failureRecord = $_
    $outcome = [ordered]@{
        status = 'failed'
        production_identity = $false
        identity = 'self-signed mechanism test only'
        failed_stage = $stage
        error_type = $_.Exception.GetType().Name
    }
} finally {
    [IO.File]::WriteAllText($stagePath, "cleanup:environment", [Text.UTF8Encoding]::new($false))
    Remove-Item Env:\PA_CODESIGN_PASSWORD -ErrorAction SilentlyContinue
    foreach ($importedThumbprint in $importedThumbprints) {
        [IO.File]::WriteAllText($stagePath, "cleanup:my-store", [Text.UTF8Encoding]::new($false))
        try {
            & (Join-Path $PSScriptRoot 'codesign-certificate.ps1') -Action Remove -Thumbprint $importedThumbprint | Out-Null
        } catch {
            $cleanupErrors.Add("CurrentUser/My:$importedThumbprint")
        }
    }
    if ($thumbprint -match '^[0-9A-Fa-f]{40}$') {
        [IO.File]::WriteAllText($stagePath, 'cleanup:My', [Text.UTF8Encoding]::new($false))
        try {
            $path = "Cert:\CurrentUser\My\$thumbprint"
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
        } catch {
            $cleanupErrors.Add("CurrentUser/My:$thumbprint")
        }
    }
    try {
        [IO.File]::WriteAllText($stagePath, "cleanup:temporary-directory", [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $runRoot) {
            Remove-Item -LiteralPath $runRoot -Recurse -Force -ErrorAction Stop
        }
    } catch {
        $cleanupErrors.Add('temporary-directory')
    }
}

$outcome.cleanup_verified = $cleanupErrors.Count -eq 0
$outcome.cleanup_errors = @($cleanupErrors)
if ($cleanupErrors.Count -gt 0) { $outcome.status = 'failed' }
$outcome | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
Remove-Item -LiteralPath $stagePath -Force -ErrorAction SilentlyContinue

if ($outcome.status -ne 'passed') {
    $detail = if ($failureRecord) { $failureRecord.Exception.Message } else { 'cleanup failed' }
    throw "Self-signed signing smoke failed during '$stage': $detail. Evidence: $ResultPath"
}
Write-Host "[self-signed-smoke] PASS (mechanism only, not production): $ResultPath"
