[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string[]]$Installer,
    [Parameter(Mandatory = $true)] [string]$UpdaterPublicKeyFile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) {
    throw 'Pinned updater signature verification requires Cargo/Rust 1.96.1.'
}
$publicKey = (Resolve-Path -LiteralPath $UpdaterPublicKeyFile).Path
$manifest = Join-Path $PSScriptRoot 'updater-signature-verifier\Cargo.toml'
$env:CARGO_TARGET_DIR = Join-Path $env:TEMP 'private-agent-updater-signature-verifier'
foreach ($path in $Installer) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    $signature = "$resolved.sig"
    if (-not (Test-Path -LiteralPath $signature -PathType Leaf)) {
        throw "Updater signature is missing for $([IO.Path]::GetFileName($resolved))."
    }
    & cargo run --quiet --locked --release --manifest-path $manifest -- $resolved $signature $publicKey
    if ($LASTEXITCODE -ne 0) {
        throw "Updater signature verification failed for $([IO.Path]::GetFileName($resolved))."
    }
}
