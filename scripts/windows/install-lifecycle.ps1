[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OldInstaller,

    [Parameter(Mandatory = $true)]
    [string]$NewInstaller,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedOldVersion,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedNewVersion,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath,

    [switch]$RequireAuthenticode,

    [ValidateSet('unclassified', 'self-signed-mechanism', 'trusted-ca-production')]
    [string]$IdentityClass = 'unclassified',

    [switch]$ProductionIdentity,

    [switch]$UpdaterSignatureVerified,

    [ValidateSet('unclassified', 'ephemeral-mechanism', 'embedded-production')]
    [string]$UpdaterVerificationScope = 'unclassified'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$startedAt = [DateTimeOffset]::UtcNow
$phases = [System.Collections.Generic.List[object]]::new()
$runId = [Guid]::NewGuid().ToString('N')
$userDataDirectory = Join-Path $env:APPDATA 'personal-assistant'
$marker = Join-Path $userDataDirectory "lifecycle-$runId.marker"
$configFile = Join-Path $userDataDirectory '.env'
$appDisplayNames = @('私人助手', 'PrivateAgent')
$script:TrackedProcessNames = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($processName in @('appsdesktop', 'PrivateAgent', '私人助手', 'personal-assistant-server')) {
    $null = $script:TrackedProcessNames.Add($processName)
}

function Add-Phase([string]$Name, [string]$Status, [string]$Detail) {
    $phases.Add([ordered]@{
        name = $Name
        status = $Status
        detail = $Detail
        at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    })
}

function Normalize-Version([string]$Version) {
    return (($Version -replace '^[vV]', '') -split '[+-]')[0].Trim()
}

function Assert-EqualVersion([string]$Actual, [string]$Expected, [string]$Label) {
    if ((Normalize-Version $Actual) -ne (Normalize-Version $Expected)) {
        throw "$Label version mismatch: expected $Expected, found $Actual"
    }
}

function Assert-Authenticode([string]$File, [string]$Label) {
    if (-not $RequireAuthenticode) {
        return [ordered]@{ status = 'not-required'; subject = $null; timestamped = $false }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $File
    if (-not $signature.SignerCertificate) {
        throw "$Label signer certificate is missing"
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "$Label signature has no trusted timestamp"
    }
    $trustVerified = $signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid
    if ($IdentityClass -eq 'self-signed-mechanism') {
        if ($signature.SignerCertificate.Subject -ne $signature.SignerCertificate.Issuer) {
            throw "$Label mechanism certificate is not self-signed"
        }
        if ($signature.Status.ToString() -notin @('Valid', 'UnknownError', 'NotTrusted')) {
            throw "$Label self-signed Authenticode status is $($signature.Status)"
        }
    } elseif (-not $trustVerified) {
        throw "$Label Authenticode status is $($signature.Status), expected Valid"
    }
    return [ordered]@{
        status = $signature.Status.ToString()
        trust_verified = $trustVerified
        verification_scope = if ($IdentityClass -eq 'self-signed-mechanism') { 'self-signed-mechanism' } else { 'trusted-ca-production' }
        subject = $signature.SignerCertificate.Subject
        thumbprint = $signature.SignerCertificate.Thumbprint
        timestamped = $true
    }
}

function Get-AppRegistration {
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    return @($roots | ForEach-Object {
        Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue
    } | Where-Object { $appDisplayNames -contains [string]$_.DisplayName })
}

function Wait-AppRegistration([bool]$Present, [int]$TimeoutSeconds = 60) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $items = @(Get-AppRegistration)
        if ($Present -and $items.Count -eq 1) {
            return $items[0]
        }
        if (-not $Present -and $items.Count -eq 0) {
            return $null
        }
        if ($items.Count -gt 1) {
            throw 'Multiple supported application uninstall registrations were found.'
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for application registration present=$Present"
}

function Get-ExecutableFromCommand([string]$Command) {
    if (-not $Command) {
        throw 'Uninstall registration has no UninstallString.'
    }
    if ($Command -match '^\s*"([^"]+\.exe)"') {
        return $Matches[1]
    }
    if ($Command -match '^\s*([^\s]+\.exe)') {
        return $Matches[1]
    }
    throw 'Unable to parse the registered uninstall executable.'
}

function Get-InstalledExecutable($Registration) {
    $installLocation = ([string]$Registration.InstallLocation).Trim().Trim('"')
    if (-not $installLocation) {
        $uninstaller = Get-ExecutableFromCommand ([string]$Registration.UninstallString)
        $installLocation = Split-Path -Parent $uninstaller
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    $mainBinaryName = ([string]$Registration.MainBinaryName).Trim().Trim('"')
    if ($mainBinaryName) {
        if ([IO.Path]::GetFileName($mainBinaryName) -ne $mainBinaryName) {
            throw 'Registered MainBinaryName must be a file name, not a path.'
        }
        $candidates.Add((Join-Path $installLocation $mainBinaryName))
    }
    if ([string]$Registration.DisplayIcon) {
        try {
            $candidates.Add((Get-ExecutableFromCommand ([string]$Registration.DisplayIcon)))
        } catch {
            # Fall back to the install directory only after both authoritative
            # NSIS registration fields have been considered.
        }
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $resolved = (Resolve-Path -LiteralPath $candidate).Path
            $null = $script:TrackedProcessNames.Add([IO.Path]::GetFileNameWithoutExtension($resolved))
            return $resolved
        }
    }

    $matches = @(Get-ChildItem -LiteralPath $installLocation -Filter '*.exe' -File |
        Where-Object {
            $_.Name -notmatch '^uninstall' -and
            $_.Name -ne 'personal-assistant-server.exe'
        })
    if ($matches.Count -ne 1) {
        throw 'Could not identify exactly one installed desktop executable.'
    }
    $resolved = (Resolve-Path -LiteralPath $matches[0].FullName).Path
    $null = $script:TrackedProcessNames.Add([IO.Path]::GetFileNameWithoutExtension($resolved))
    return $resolved
}

function Get-InstalledVersion($Registration, [string]$Executable) {
    $displayVersion = [string]$Registration.DisplayVersion
    if ($displayVersion) {
        return $displayVersion
    }
    $versionInfo = (Get-Item -LiteralPath $Executable).VersionInfo
    if ($versionInfo.ProductVersion) {
        return $versionInfo.ProductVersion
    }
    return $versionInfo.FileVersion
}

function Invoke-Nsis([string]$Installer, [string]$Label) {
    $process = Start-Process -FilePath $Installer -ArgumentList '/S' -PassThru
    if (-not $process.WaitForExit(300000)) {
        $process.Kill()
        throw "$Label timed out after 300 seconds"
    }
    if ($process.ExitCode -ne 0) {
        throw "$Label returned exit code $($process.ExitCode)"
    }
}

function Get-ResidualProcesses {
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $script:TrackedProcessNames.Contains($_.ProcessName)
    })
}

function Assert-NoResidualProcesses {
    $residual = @(Get-ResidualProcesses)
    if ($residual.Count -gt 0) {
        throw "Residual application processes remain: $($residual.ProcessName -join ', ')"
    }
}

function Wait-NoResidualProcesses([int]$TimeoutSeconds = 60) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $residual = @(Get-ResidualProcesses)
        if ($residual.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    Assert-NoResidualProcesses
}

function Start-And-AssertRuntime([string]$Executable, [string]$Label) {
    $main = Start-Process -FilePath $Executable -PassThru
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    do {
        $main.Refresh()
        if ($main.HasExited) {
            throw "$Label exited before its packaged sidecar became ready"
        }
        $sidecars = @(Get-Process -Name 'personal-assistant-server' -ErrorAction SilentlyContinue)
        if ($sidecars.Count -gt 0) {
            return [ordered]@{
                main_pid = $main.Id
                sidecar_pids = @($sidecars.Id)
            }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "$Label did not start its packaged sidecar within 120 seconds"
}

function Stop-ResidualProcessesBestEffort {
    Get-ResidualProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
}

$result = [ordered]@{
    schema_version = 1
    run_id = $runId
    status = 'failed'
    clean_machine = $false
    identity_class = $IdentityClass
    production_identity = [bool]$ProductionIdentity
    updater_signature_verified = [bool]$UpdaterSignatureVerified
    updater_verification_scope = $UpdaterVerificationScope
    old_version = $null
    new_version = $null
    data_preserved_on_upgrade = $false
    data_preserved_on_uninstall = $false
    old_runtime_started = $false
    new_runtime_started = $false
    upgrade_closed_running_processes = $false
    uninstall_closed_running_processes = $false
    authenticode = [ordered]@{}
    artifacts = [ordered]@{}
    install_identity = [ordered]@{}
    host = [ordered]@{
        os_version = [Environment]::OSVersion.VersionString
        architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        actions_image_os = $env:ImageOS
        actions_image_version = $env:ImageVersion
    }
    phases = $phases
    started_at_utc = $startedAt.ToString('o')
    finished_at_utc = $null
    error = $null
}

$exitCode = 1
try {
    if ($ProductionIdentity -and $IdentityClass -ne 'trusted-ca-production') {
        throw 'ProductionIdentity requires IdentityClass=trusted-ca-production.'
    }
    if (-not $ProductionIdentity -and $IdentityClass -eq 'trusted-ca-production') {
        throw 'trusted-ca-production evidence must set ProductionIdentity.'
    }
    if (-not $UpdaterSignatureVerified) {
        throw 'Updater signature verification must pass before lifecycle execution.'
    }
    if ($ProductionIdentity -and $UpdaterVerificationScope -ne 'embedded-production') {
        throw 'Production evidence requires updater verification against the embedded public key.'
    }
    $old = (Resolve-Path -LiteralPath $OldInstaller).Path
    $new = (Resolve-Path -LiteralPath $NewInstaller).Path
    $result.artifacts['old'] = [ordered]@{
        file_name = [IO.Path]::GetFileName($old)
        sha256 = (Get-FileHash -LiteralPath $old -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = (Get-Item -LiteralPath $old).Length
    }
    $result.artifacts['new'] = [ordered]@{
        file_name = [IO.Path]::GetFileName($new)
        sha256 = (Get-FileHash -LiteralPath $new -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = (Get-Item -LiteralPath $new).Length
    }
    if ((Normalize-Version $ExpectedOldVersion) -eq (Normalize-Version $ExpectedNewVersion)) {
        throw 'Old and new expected versions must be different.'
    }
    if (@(Get-AppRegistration).Count -ne 0) {
        throw 'PrivateAgent is already installed; lifecycle tests require a clean machine snapshot.'
    }
    if (Test-Path -LiteralPath $userDataDirectory) {
        throw 'Application user data already exists; lifecycle tests require a clean machine snapshot.'
    }
    Assert-NoResidualProcesses
    $result.clean_machine = $true
    Add-Phase 'preflight' 'passed' 'No existing installation, process, or application user data was found.'

    $result.authenticode['old'] = Assert-Authenticode $old 'Old installer'
    $result.authenticode['new'] = Assert-Authenticode $new 'New installer'
    Add-Phase 'authenticode' 'passed' 'Both installer signatures satisfy the configured policy.'

    Invoke-Nsis $old 'Old installer'
    $oldRegistration = Wait-AppRegistration $true
    $oldExecutable = Get-InstalledExecutable $oldRegistration
    $result.install_identity['old'] = [ordered]@{
        display_name = [string]$oldRegistration.DisplayName
        main_binary_name = [IO.Path]::GetFileName($oldExecutable)
    }
    $oldVersion = Get-InstalledVersion $oldRegistration $oldExecutable
    Assert-EqualVersion $oldVersion $ExpectedOldVersion 'Installed old'
    $result.old_version = $oldVersion
    Add-Phase 'install' 'passed' "Installed PrivateAgent $oldVersion silently."

    $markerDirectory = Split-Path -Parent $marker
    $null = New-Item -ItemType Directory -Path $markerDirectory -Force
    [IO.File]::WriteAllText($marker, "PrivateAgent lifecycle marker $runId", [Text.UTF8Encoding]::new($false))
    $lifecycleConfig = @"
PA_DB_URL=mysql+aiomysql://lifecycle:unused@127.0.0.1:1/pa_lifecycle?charset=utf8mb4
PA_OLLAMA_BASE_URL=http://127.0.0.1:1
PA_LLM_MODEL=qwen2
PA_EMBED_MODEL=bge-m3
"@
    [IO.File]::WriteAllText($configFile, $lifecycleConfig, [Text.UTF8Encoding]::new($false))
    $configHash = (Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash

    $oldRuntime = Start-And-AssertRuntime $oldExecutable 'Installed old application'
    $result.old_runtime_started = $true
    Add-Phase 'old-runtime' 'passed' "Started main PID $($oldRuntime.main_pid) and packaged sidecar."

    Invoke-Nsis $new 'New installer'
    Wait-NoResidualProcesses
    $result.upgrade_closed_running_processes = $true
    $newRegistration = Wait-AppRegistration $true
    $newExecutable = Get-InstalledExecutable $newRegistration
    $result.install_identity['new'] = [ordered]@{
        display_name = [string]$newRegistration.DisplayName
        main_binary_name = [IO.Path]::GetFileName($newExecutable)
    }
    $newVersion = Get-InstalledVersion $newRegistration $newExecutable
    Assert-EqualVersion $newVersion $ExpectedNewVersion 'Installed new'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'User-data marker was lost during upgrade.'
    }
    if (-not (Test-Path -LiteralPath $configFile -PathType Leaf) -or
        (Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash -ne $configHash) {
        throw 'Connection configuration was lost or modified during upgrade.'
    }
    $result.new_version = $newVersion
    $result.data_preserved_on_upgrade = $true
    Add-Phase 'upgrade' 'passed' "Upgraded the running app to PrivateAgent $newVersion, closed old processes, and preserved user data."

    $newRuntime = Start-And-AssertRuntime $newExecutable 'Installed new application'
    $result.new_runtime_started = $true
    Add-Phase 'new-runtime' 'passed' "Started main PID $($newRuntime.main_pid) and packaged sidecar."

    $uninstaller = Get-ExecutableFromCommand ([string]$newRegistration.UninstallString)
    $installDirectory = Split-Path -Parent $uninstaller
    Invoke-Nsis $uninstaller 'Uninstaller'
    Wait-NoResidualProcesses
    $result.uninstall_closed_running_processes = $true
    $null = Wait-AppRegistration $false
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
    while ((Test-Path -LiteralPath $installDirectory) -and [DateTimeOffset]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if (Test-Path -LiteralPath $installDirectory) {
        throw 'Application installation directory remains after uninstall.'
    }
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'User-data marker was removed by uninstall.'
    }
    if (-not (Test-Path -LiteralPath $configFile -PathType Leaf) -or
        (Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash -ne $configHash) {
        throw 'Connection configuration was removed or modified by uninstall.'
    }
    Assert-NoResidualProcesses
    $result.data_preserved_on_uninstall = $true
    Add-Phase 'uninstall' 'passed' 'Application files were removed, user data was preserved, and no process remained.'

    $result.status = 'passed'
    $exitCode = 0
} catch {
    $result.error = $_.Exception.Message
    Add-Phase 'failure' 'failed' $_.Exception.Message
} finally {
    if ($exitCode -ne 0) { Stop-ResidualProcessesBestEffort }
    $result.finished_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $resultDirectory = Split-Path -Parent $ResultPath
    if ($resultDirectory) {
        $null = New-Item -ItemType Directory -Path $resultDirectory -Force
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    Write-Host "[lifecycle] status=$($result.status) result=$ResultPath"
}

exit $exitCode
