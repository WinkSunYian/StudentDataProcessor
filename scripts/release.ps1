<#
.SYNOPSIS
    打包 StudentDataProcessor 并发布到 GitHub Releases。

.DESCRIPTION
    流程:
      1. 校验 version.py 的 APP_VERSION 与 -Version 一致(唯一版本源)
      2. 要求工作区干净、当前分支已推送
      3. PyInstaller 打包(跳过可加 -SkipBuild)
      4. 校验产物:exe 存在、Resources 已打包、没有混入 data\
      5. 压缩成 dist\StudentDataProcessor-<版本>-win64.zip 并算 SHA-256
      6. 打 tag 并推送
      7. gh release create 上传 zip

    客户端用 GitHub 自动给出的 asset.digest(sha256) 校验,不读本脚本算的哈希;
    这里打印哈希只是为了人工核对。

.PARAMETER Version
    版本号,如 1.1.0(会自动补 v 前缀)。必须与 version.py 里的 APP_VERSION 一致。

.EXAMPLE
    # 改完 version.py 并提交后:
    .\scripts\release.ps1 -Version 1.1.0 -Notes "1. 新增自动更新`n2. 修复同步"
.EXAMPLE
    .\scripts\release.ps1 -Version 1.1.0 -SkipPublish   # 只打包不发版
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [string]$Notes = "",

    [switch]$SkipBuild,
    [switch]$SkipPublish,

    [string]$Repo = "WinkSunYian/StudentDataProcessor"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$tag = "v$Version"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[失败] $msg" -ForegroundColor Red
    exit 1
}

function Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

# ------------------------------------------------------------------ 1. 版本号
Step "1/7 校验版本号"
$versionFile = Join-Path $root "version.py"
if (-not (Test-Path $versionFile)) { Fail "找不到 version.py" }

$content = Get-Content $versionFile -Raw -Encoding UTF8
if ($content -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    Fail "version.py 里没找到 APP_VERSION = `"x.y.z`""
}
$localVersion = $Matches[1]
if ($localVersion -ne $Version) {
    Fail "version.py 是 $localVersion,命令行参数是 $Version。先改 version.py 再提交,保证两边一致。"
}
Write-Host "    APP_VERSION = $localVersion  tag = $tag"

# ------------------------------------------------------------------ 2. 仓库状态
Step "2/7 检查仓库状态"
if (-not (Test-Path (Join-Path $root ".git"))) { Fail "当前目录不是 git 仓库" }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host $dirty
    Fail "工作区不干净,先 commit(或 stash)再发布。"
}

$branch = git rev-parse --abbrev-ref HEAD
$unpushed = git log --oneline "origin/$branch..$branch" 2>$null
if ($unpushed) {
    Write-Host $unpushed
    Fail "分支 $branch 还有未推送的提交,先 git push。"
}

if (git tag -l $tag) { Fail "tag $tag 已存在,换个版本号或先删掉远端 tag。" }
Write-Host "    分支 $branch 干净,tag $tag 可用"

# ------------------------------------------------------------------ 3. 打包
$distDir = Join-Path $root "dist\StudentDataProcessor"
$exePath = Join-Path $distDir "StudentDataProcessor.exe"

if ($SkipBuild) {
    Step "3/7 跳过打包(-SkipBuild)"
    if (-not (Test-Path $exePath)) { Fail "跳过打包但找不到 $exePath" }
} else {
    Step "3/7 PyInstaller 打包"
    $makespec = Join-Path $root "venv\Scripts\pyi-makespec.exe"
    $pyinstaller = Join-Path $root "venv\Scripts\pyinstaller.exe"
    if (-not (Test-Path $pyinstaller)) { Fail "找不到 $pyinstaller" }

    # spec 不入库,没有就现场生成(参数必须与项目约定一致)
    if (-not (Test-Path (Join-Path $root "StudentDataProcessor.spec"))) {
        Write-Host "    生成 StudentDataProcessor.spec ..."
        if (Test-Path $makespec) {
            & $makespec --onedir --windowed --noupx --icon "Resources\icon.ico" `
                --add-data "Resources;Resources" --name StudentDataProcessor main.py
        } else {
            & $pyinstaller --onedir --windowed --noupx --icon "Resources\icon.ico" `
                --add-data "Resources;Resources" --name StudentDataProcessor main.py
        }
        if ($LASTEXITCODE -ne 0) { Fail "生成 spec 失败" }
    }

    & $pyinstaller --noconfirm StudentDataProcessor.spec
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller 打包失败(退出码 $LASTEXITCODE)" }
}

# ------------------------------------------------------------------ 4. 校验产物
Step "4/7 校验产物"
if (-not (Test-Path $exePath)) { Fail "找不到 $exePath" }

$iconCandidates = @(
    (Join-Path $distDir "_internal\Resources\icon.ico"),
    (Join-Path $distDir "Resources\icon.ico")
)
if (-not ($iconCandidates | Where-Object { Test-Path $_ })) {
    Fail "包里没有 Resources\icon.ico —— spec 的 --add-data 漏了"
}
if (Test-Path (Join-Path $distDir "data")) {
    Fail "包里混进了 data\,检查 spec 是否带上了 data"
}
if (Test-Path (Join-Path $distDir "sessionid.txt")) {
    Fail "包里混进了 sessionid.txt"
}

$distBytes = (Get-ChildItem $distDir -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("    {0}  ({1} MB / {2} 个文件)" -f $exePath,
    [math]::Round($distBytes / 1MB, 1),
    (Get-ChildItem $distDir -Recurse -File).Count)

# ------------------------------------------------------------------ 5. 压缩
Step "5/7 生成 zip"
$zipName = "StudentDataProcessor-$Version-win64.zip"
$zipPath = Join-Path $root "dist\$zipName"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

# -Path 指向目录本身,使 zip 根是 StudentDataProcessor\,解压后由更新器自动下沉一层
Compress-Archive -Path $distDir -DestinationPath $zipPath -CompressionLevel Fastest -Force
if (-not (Test-Path $zipPath)) { Fail "压缩失败" }

$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
$zipMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "    $zipPath"
Write-Host "    $zipMB MB"
Write-Host "    sha256:$hash"

if ($SkipPublish) {
    Write-Host ""
    Write-Host "[完成] 已打包压缩,跳过发布(-SkipPublish)" -ForegroundColor Green
    exit 0
}

# ------------------------------------------------------------------ 6. 打 tag
Step "6/7 推送 tag"
git tag $tag
if ($LASTEXITCODE -ne 0) { Fail "git tag 失败" }

git push origin $branch
if ($LASTEXITCODE -ne 0) { Fail "推送分支 $branch 失败" }

git push origin $tag
if ($LASTEXITCODE -ne 0) { Fail "推送 tag $tag 失败" }

# ------------------------------------------------------------------ 7. 发布
Step "7/7 创建 GitHub Release"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Fail "未安装 gh CLI,请先执行: winget install GitHub.cli"
}
gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "gh 未登录,请执行: gh auth login" }

$releaseNotes = $Notes
if ([string]::IsNullOrWhiteSpace($releaseNotes)) { $releaseNotes = "版本 $tag" }

gh release create $tag $zipPath `
    --repo $Repo `
    --title $tag `
    --notes $releaseNotes
if ($LASTEXITCODE -ne 0) { Fail "创建 Release 失败(退出码 $LASTEXITCODE)" }

$url = "https://github.com/$Repo/releases/tag/$tag"
Write-Host ""
Write-Host "[完成] $url" -ForegroundColor Green
Write-Host "       上传完成后,旧版本会在启动 3 秒后自动检测到新版本。"
