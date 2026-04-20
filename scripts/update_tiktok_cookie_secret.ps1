param(
    [string]$CookiePath = "src/www.tiktok.com_cookies.txt",
    [string]$SecretName = "TIKTOK_COOKIES_TXT_B64",
    [switch]$Login
)

$ErrorActionPreference = "Stop"

function Fail($Message) {
    Write-Error $Message
    exit 1
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Fail "GitHub CLI (gh) is not installed. Install it once from https://cli.github.com/ and rerun this script."
}

if ($Login) {
    gh auth login
}

gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "GitHub CLI is not logged in. Run: gh auth login"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$fullCookiePath = if ([IO.Path]::IsPathRooted($CookiePath)) {
    $CookiePath
} else {
    Join-Path $repoRoot $CookiePath
}

if (-not (Test-Path -LiteralPath $fullCookiePath)) {
    Fail "Cookie file not found: $fullCookiePath"
}

$cookieFile = Get-Item -LiteralPath $fullCookiePath
if ($cookieFile.Length -le 0) {
    Fail "Cookie file is empty: $fullCookiePath"
}

$encoded = [Convert]::ToBase64String([IO.File]::ReadAllBytes($cookieFile.FullName))
$encoded | gh secret set $SecretName --body-file -

if ($LASTEXITCODE -ne 0) {
    Fail "Failed to update GitHub secret $SecretName."
}

Write-Host "Updated GitHub Actions secret: $SecretName"
Write-Host "Cookie source: $($cookieFile.FullName)"
Write-Host "The cookie value was not printed."
