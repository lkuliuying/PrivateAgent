[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedThumbprint,

    [switch]$RequireTimestamp,

    [switch]$AllowUntrustedSelfSigned
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw 'Authenticode target does not exist.'
}
$expected = ($ExpectedThumbprint -replace '\s', '').ToUpperInvariant()
if ($expected -notmatch '^[0-9A-F]{40}$') {
    throw 'Expected thumbprint must contain exactly 40 hexadecimal characters.'
}

$signature = Get-AuthenticodeSignature -LiteralPath $Path
if (-not $signature.SignerCertificate) {
    throw 'Authenticode signer certificate is missing.'
}
$actual = ($signature.SignerCertificate.Thumbprint -replace '\s', '').ToUpperInvariant()
if ($actual -ne $expected) {
    throw "Authenticode signer thumbprint mismatch (expected ...$($expected.Substring(28)), actual ...$($actual.Substring(28)))."
}
$trustVerified = $signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid
if ($AllowUntrustedSelfSigned) {
    if ($signature.SignerCertificate.Subject -ne $signature.SignerCertificate.Issuer) {
        throw 'Mechanism verification requires an explicitly self-signed test certificate.'
    }
    if ($signature.Status.ToString() -notin @('Valid', 'UnknownError', 'NotTrusted')) {
        throw "Self-signed Authenticode integrity status is $($signature.Status)."
    }
} elseif (-not $trustVerified) {
    throw "Authenticode status is $($signature.Status), expected Valid."
}
$timestamped = $null -ne $signature.TimeStamperCertificate
if ($RequireTimestamp -and -not $timestamped) {
    throw 'Authenticode signature has no trusted RFC3161 timestamp.'
}

$tamperDetected = $null
if ($AllowUntrustedSelfSigned) {
    $tampered = Join-Path $env:TEMP "private-agent-authenticode-tamper-$([Guid]::NewGuid().ToString('N')).exe"
    try {
        Copy-Item -LiteralPath $Path -Destination $tampered
        $stream = [IO.File]::Open(
            $tampered,
            [IO.FileMode]::Open,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
        try {
            if ($stream.Length -lt 2) { throw 'Authenticode target is too small for a tamper check.' }
            $offset = [Math]::Max(1, [Math]::Min(4096, [int]($stream.Length / 2)))
            $null = $stream.Seek($offset, [IO.SeekOrigin]::Begin)
            $original = $stream.ReadByte()
            if ($original -lt 0) { throw 'Unable to read the Authenticode tamper-check byte.' }
            $null = $stream.Seek($offset, [IO.SeekOrigin]::Begin)
            $stream.WriteByte($original -bxor 1)
            $stream.Flush($true)
        } finally {
            $stream.Dispose()
        }
        $tamperedSignature = Get-AuthenticodeSignature -LiteralPath $tampered
        $tamperDetected = $tamperedSignature.Status -eq [System.Management.Automation.SignatureStatus]::HashMismatch
        if (-not $tamperDetected) {
            throw "Tampered Authenticode copy returned $($tamperedSignature.Status), expected HashMismatch."
        }
    } finally {
        Remove-Item -LiteralPath $tampered -Force -ErrorAction SilentlyContinue
    }
}

[ordered]@{
    status = $signature.Status.ToString()
    trust_verified = $trustVerified
    verification_scope = if ($AllowUntrustedSelfSigned) { 'self-signed-mechanism' } else { 'trusted-ca-production' }
    signature_type = $signature.SignatureType.ToString()
    thumbprint = $actual
    subject = $signature.SignerCertificate.Subject
    timestamped = $timestamped
    timestamp_subject = if ($timestamped) { $signature.TimeStamperCertificate.Subject } else { $null }
    tamper_detected = $tamperDetected
} | ConvertTo-Json -Compress
