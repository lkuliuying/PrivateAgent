param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Source', 'Assets')]
    [string]$Mode,
    [string[]]$AssetPaths = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-CheckedNative {
    param([string]$Command, [string[]]$Arguments)
    $result = & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE; release verification stopped."
    }
    return ($result -join "`n")
}

$tag = $env:RELEASE_TAG
if ([string]::IsNullOrWhiteSpace($tag) -or $tag -match '[\r\n]') {
    throw 'RELEASE_TAG must contain one existing tag name.'
}
# 标签只作为参数传递；完整引用避免与分支、选项或缩写提交混淆。
$tagRef = "refs/tags/$tag"
$null = Invoke-CheckedNative git @('check-ref-format', $tagRef)

if ($Mode -eq 'Source') {
    if ($env:RELEASE_EVENT_NAME -notin @('release', 'workflow_dispatch')) {
        throw 'Unsupported release event.'
    }
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_OUTPUT)) {
        throw 'GITHUB_OUTPUT is required to record verified source metadata.'
    }
    $headCommit = Invoke-CheckedNative git @('rev-parse', '--verify', 'HEAD^{commit}')
    # 同时支持轻量标签和附注标签，比较最终提交而非标签对象自身。
    $tagCommit = Invoke-CheckedNative git @('rev-parse', '--verify', "$tagRef^{commit}")
    if ($headCommit -notmatch '\A[0-9a-f]{40}([0-9a-f]{24})?\z' -or $headCommit -cne $tagCommit) {
        throw 'Checked-out HEAD does not match the release tag commit.'
    }
    if ($env:RELEASE_EVENT_NAME -eq 'release' -and $headCommit -ine $env:RELEASE_EVENT_SHA) {
        throw 'Checked-out HEAD does not match the release event commit.'
    }
    $config = Get-Content -LiteralPath 'apps/desktop/src-tauri/tauri.conf.json' -Raw | ConvertFrom-Json
    $version = $config.version
    # 限定单行版本，避免输出文件或后续产物名称接受额外控制字符。
    if ($version -isnot [string] -or $version -notmatch '\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?\z') {
        throw 'Application version is not a valid release version.'
    }
    if ($tag -cne "v$version" -and $tag -cne $version) {
        throw 'Release tag does not match the application version.'
    }
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Value @(
        "tag=$tag", "version=$version", "commit=$headCommit"
    )
    Write-Host "Verified release source: $tag at $headCommit"
    return
}

if ([string]::IsNullOrWhiteSpace($env:GITHUB_REPOSITORY) -or $AssetPaths.Count -eq 0) {
    throw 'Repository and local asset paths are required before uploading.'
}
$names = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($assetPath in $AssetPaths) {
    $asset = Get-Item -LiteralPath $assetPath
    if ($asset -isnot [System.IO.FileInfo] -or $asset.Length -eq 0) {
        throw 'Every release asset must be a non-empty regular file.'
    }
    if (-not $names.Add($asset.Name)) {
        throw "Duplicate local release asset name: $($asset.Name)"
    }
}

# 读取失败或响应结构不完整时停止，不能把未知状态当作没有附件。
$json = Invoke-CheckedNative gh @('release', 'view', $tag, '--repo', $env:GITHUB_REPOSITORY, '--json', 'tagName,assets')
$release = $json | ConvertFrom-Json -AsHashtable
if ($release -isnot [System.Collections.IDictionary] -or
    -not $release.Contains('tagName') -or $release.tagName -cne $tag -or
    -not $release.Contains('assets') -or $release.assets -isnot [array]) {
    throw 'GitHub Release metadata is incomplete or belongs to another tag.'
}
foreach ($asset in $release.assets) {
    if ($asset -isnot [System.Collections.IDictionary] -or
        -not $asset.Contains('name') -or $asset.name -isnot [string] -or
        [string]::IsNullOrWhiteSpace($asset.name)) {
        throw 'GitHub Release asset metadata is incomplete.'
    }
    if ($names.Contains($asset.name)) {
        throw "Release asset already exists; refusing to overwrite: $($asset.name)"
    }
}
Write-Host 'Verified release assets: all local files exist and no names are already published.'
