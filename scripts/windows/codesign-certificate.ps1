[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Inspect', 'Import', 'List', 'Remove')]
    [string]$Action,

    [string]$Thumbprint,
    [string]$PfxPath,
    [string]$ExpectedSubject,

    [switch]$RequireTrustedChain
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Normalize-Thumbprint([string]$Value) {
    $normalized = ($Value -replace '\s', '').ToUpperInvariant()
    if ($normalized -notmatch '^[0-9A-F]{40}$') {
        throw 'Certificate thumbprint must contain exactly 40 hexadecimal characters.'
    }
    return $normalized
}

function Get-CodeSigningCertificate([string]$NormalizedThumbprint) {
    $path = "Cert:\CurrentUser\My\$NormalizedThumbprint"
    if (-not (Test-Path -LiteralPath $path)) {
        throw 'The configured certificate was not found in Cert:\CurrentUser\My.'
    }
    $certificate = Get-Item -LiteralPath $path
    $codeSigningOid = '1.3.6.1.5.5.7.3.3'
    $hasCodeSigningEku = @($certificate.Extensions | Where-Object {
        $_.Oid.Value -eq '2.5.29.37' -and
        @($_.EnhancedKeyUsages | Where-Object { $_.Value -eq $codeSigningOid }).Count -gt 0
    }).Count -gt 0
    if (-not $hasCodeSigningEku) {
        throw 'The configured certificate does not permit code signing.'
    }
    if (-not $certificate.HasPrivateKey) {
        throw 'The configured certificate has no accessible private key.'
    }
    $now = Get-Date
    if ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
        throw 'The configured certificate is not currently valid.'
    }
    if ($ExpectedSubject -and
        -not [string]::Equals($certificate.Subject, $ExpectedSubject, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The certificate subject does not match PA_CODESIGN_EXPECTED_SUBJECT.'
    }
    if ($RequireTrustedChain) {
        if ([string]::Equals($certificate.Subject, $certificate.Issuer, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Self-signed certificates are forbidden for production releases.'
        }
        $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
        try {
            $chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::Online
            $chain.ChainPolicy.RevocationFlag = [Security.Cryptography.X509Certificates.X509RevocationFlag]::ExcludeRoot
            $chain.ChainPolicy.VerificationFlags = [Security.Cryptography.X509Certificates.X509VerificationFlags]::NoFlag
            $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(15)
            if (-not $chain.Build($certificate)) {
                throw 'The production code-signing certificate chain is not trusted.'
            }
        } finally {
            $chain.Dispose()
        }
    }
    return $certificate
}

switch ($Action) {
    'List' {
        [ordered]@{
            thumbprints = @(
                Get-ChildItem Cert:\CurrentUser\My -ErrorAction Stop |
                    ForEach-Object { Normalize-Thumbprint $_.Thumbprint }
            )
        } | ConvertTo-Json -Compress
    }

    'Import' {
        if (-not $PfxPath -or -not (Test-Path -LiteralPath $PfxPath -PathType Leaf)) {
            throw 'PFX file not found.'
        }
        if (-not $env:PA_CODESIGN_PASSWORD) {
            throw 'PA_CODESIGN_PASSWORD is required to import a PFX.'
        }

        # Read the leaf certificate with ephemeral key material first so we can
        # avoid deleting a certificate that already existed before this run.
        $flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
        $collection = [System.Security.Cryptography.X509Certificates.X509Certificate2Collection]::new()
        $collection.Import($PfxPath, $env:PA_CODESIGN_PASSWORD, $flags)
        $leaf = @($collection | Where-Object {
            $_.HasPrivateKey -and @($_.Extensions | Where-Object {
                $_.Oid.Value -eq '2.5.29.37' -and
                @($_.EnhancedKeyUsages | Where-Object {
                    $_.Value -eq '1.3.6.1.5.5.7.3.3'
                }).Count -gt 0
            }).Count -gt 0
        })
        if ($leaf.Count -ne 1) {
            throw 'PFX must contain exactly one private-key code-signing certificate.'
        }

        $normalized = Normalize-Thumbprint $leaf[0].Thumbprint
        $candidateThumbprints = @($collection | ForEach-Object {
            Normalize-Thumbprint $_.Thumbprint
        } | Select-Object -Unique)
        $presentBefore = @{}
        foreach ($candidate in $candidateThumbprints) {
            $presentBefore[$candidate] = Test-Path -LiteralPath "Cert:\CurrentUser\My\$candidate"
        }
        $storePath = "Cert:\CurrentUser\My\$normalized"
        try {
            if (-not $presentBefore[$normalized]) {
                $securePassword = ConvertTo-SecureString $env:PA_CODESIGN_PASSWORD -AsPlainText -Force
                $null = Import-PfxCertificate `
                    -FilePath $PfxPath `
                    -CertStoreLocation 'Cert:\CurrentUser\My' `
                    -Password $securePassword `
                    -Exportable:$false
            }
            $importedThumbprints = @($candidateThumbprints | Where-Object {
                -not $presentBefore[$_] -and (Test-Path -LiteralPath "Cert:\CurrentUser\My\$_")
            })
            $null = Get-CodeSigningCertificate $normalized
        } catch {
            # Transactional rollback is mandatory: Python cannot clean entries
            # when Import fails before it returns imported_thumbprints.
            $rollbackFailures = [System.Collections.Generic.List[string]]::new()
            foreach ($candidate in $candidateThumbprints) {
                $candidatePath = "Cert:\CurrentUser\My\$candidate"
                if (-not $presentBefore[$candidate] -and (Test-Path -LiteralPath $candidatePath)) {
                    try {
                        Remove-Item -LiteralPath $candidatePath -Force
                    } catch {
                        $rollbackFailures.Add($candidate)
                    }
                }
            }
            if ($rollbackFailures.Count -gt 0) {
                throw 'PFX import validation failed and transactional certificate rollback was incomplete.'
            }
            throw
        }
        [ordered]@{
            thumbprint = $normalized
            imported = $importedThumbprints -contains $normalized
            imported_thumbprints = $importedThumbprints
        } | ConvertTo-Json -Compress
    }

    'Inspect' {
        $normalized = Normalize-Thumbprint $Thumbprint
        $certificate = Get-CodeSigningCertificate $normalized
        if ($ExpectedSubject -and
            -not [string]::Equals($certificate.Subject, $ExpectedSubject, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'The certificate subject does not match PA_CODESIGN_EXPECTED_SUBJECT.'
        }
        [ordered]@{
            thumbprint = $normalized
            subject = $certificate.Subject
            issuer = $certificate.Issuer
            not_before = $certificate.NotBefore.ToUniversalTime().ToString('o')
            not_after = $certificate.NotAfter.ToUniversalTime().ToString('o')
            has_private_key = $certificate.HasPrivateKey
        } | ConvertTo-Json -Compress
    }

    'Remove' {
        $normalized = Normalize-Thumbprint $Thumbprint
        $path = "Cert:\CurrentUser\My\$normalized"
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
        [ordered]@{ removed = -not (Test-Path -LiteralPath $path) } | ConvertTo-Json -Compress
    }
}
