param(
    [string]$ServerBaseUrl = "http://127.0.0.1:8080",
    [string]$TargetDir = ".\\storage\\updates"
)

$ErrorActionPreference = "Stop"

$version = Invoke-RestMethod -Uri "$ServerBaseUrl/api/version" -Method Get
if (-not $version.update_available) {
    Write-Host "目前已是最新版本：$($version.current_version)"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($version.latest_package_url)) {
    throw "有新版本，但未設定 latest_package_url。"
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$fileName = Split-Path $version.latest_package_url -Leaf
$targetPath = Join-Path $TargetDir $fileName

Invoke-WebRequest -Uri $version.latest_package_url -OutFile $targetPath
Write-Host "已下載更新封包：$targetPath"
Write-Host "請驗證封包後，以部署流程取代目前程式並重啟服務。"
