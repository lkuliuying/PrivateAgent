[CmdletBinding()]
param(
    [ValidateSet('Signing', 'HyperV', 'Sandbox', 'All')]
    [string]$Mode = 'All',
    [string]$VMName,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $checks.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail })
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
    if ($matches.Count -gt 0) { return $matches[0].FullName }
    return $null
}

if ($Mode -in @('Signing', 'All')) {
    $signTool = Find-SignTool
    Add-Check 'signtool' ($null -ne $signTool) $(if ($signTool) { $signTool } else { 'Windows SDK Signing Tools not found' })

    $thumbprint = ($env:PA_CODESIGN_THUMBPRINT -replace '\s', '').ToUpperInvariant()
    $pfx = $env:PA_CODESIGN_PFX
    $hasSource = $false
    if ($thumbprint) {
        $hasSource = $thumbprint -match '^[0-9A-F]{40}$' -and
            (Test-Path -LiteralPath "Cert:\CurrentUser\My\$thumbprint")
        Add-Check 'production-certificate' $hasSource $(if ($hasSource) { 'CurrentUser certificate-store thumbprint is available' } else { 'Configured thumbprint is invalid or unavailable' })
    } elseif ($pfx) {
        $hasSource = (Test-Path -LiteralPath $pfx -PathType Leaf) -and [bool]$env:PA_CODESIGN_PASSWORD
        Add-Check 'production-certificate' $hasSource $(if ($hasSource) { 'Ephemeral PFX source and in-memory password are available' } else { 'PFX or in-memory password is unavailable' })
    } else {
        Add-Check 'production-certificate' $false 'No production Authenticode certificate is configured'
    }
    Add-Check 'production-expected-subject' ([bool]$env:PA_CODESIGN_EXPECTED_SUBJECT) 'PA_CODESIGN_EXPECTED_SUBJECT must pin the release identity'
    Add-Check 'password-file-policy' (-not [bool]$env:PA_CODESIGN_PASSWORD_FILE) 'Password files are forbidden for production Authenticode signing'
    Add-Check 'updater-private-key' ([bool]$env:TAURI_SIGNING_PRIVATE_KEY) 'TAURI updater private key must be supplied through the environment'
    Add-Check 'updater-key-password' ([bool]$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) 'TAURI updater key password must be supplied through the environment'
}

if ($Mode -in @('HyperV', 'All')) {
    $getVm = Get-Command Get-VM -ErrorAction SilentlyContinue
    $vmms = Get-Service vmms -ErrorAction SilentlyContinue
    Add-Check 'hyper-v-module' ($null -ne $getVm) 'Hyper-V PowerShell module is required'
    Add-Check 'hyper-v-service' ($null -ne $vmms -and $vmms.Status -eq 'Running') 'Hyper-V Virtual Machine Management must be running'
    if ($VMName -and $getVm) {
        $vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
        Add-Check 'hyper-v-target' ($null -ne $vm) "Requested VM: $VMName"
    }
}

if ($Mode -in @('Sandbox', 'All')) {
    $sandbox = Join-Path $env:WINDIR 'System32\WindowsSandbox.exe'
    Add-Check 'windows-sandbox' (Test-Path -LiteralPath $sandbox -PathType Leaf) 'Windows Sandbox optional feature and executable are required'
}

$failed = @($checks | Where-Object { -not $_.passed }).Count
$result = [ordered]@{
    mode = $Mode
    passed = $failed -eq 0
    failed = $failed
    checks = $checks
}
if ($Json) {
    $result | ConvertTo-Json -Depth 5
} else {
    foreach ($check in $checks) {
        $mark = if ($check.passed) { 'PASS' } else { 'FAIL' }
        Write-Host "[$mark] $($check.name): $($check.detail)"
    }
}
if ($failed -gt 0) { exit 1 }
