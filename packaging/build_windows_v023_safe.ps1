# Run Build first, validate the resulting GUI, then run Package with the
# frozen_smoke_gate.json recording the SHA256 of the EXE actually tested.
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Package')][string]$Stage = 'Build',
    [string]$SmokeEvidence = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [Runtime.InteropServices.OSPlatform]::Windows) -or
    -not [Environment]::Is64BitOperatingSystem) {
    throw 'This script requires Windows x64.'
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$packageName = 'MultiViewSyncPlayer-v0.2.3-test2-win64'
$distRoot = Join-Path $repoRoot 'dist'
$target = Join-Path $distRoot $packageName
$zip = Join-Path $distRoot "$packageName.zip"
$report = Join-Path $repoRoot 'benchmark_results\windows_v023_test2'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$spec = Join-Path $repoRoot 'packaging\mvsp_windows.spec'

# Validate before creating logs or invoking PyInstaller; never overwrite or
# remove a completed package, archive, or any shared build/dist directory.
if (Test-Path -LiteralPath $zip) { throw "ZIP already exists: $zip" }
if ($Stage -eq 'Build' -and (Test-Path -LiteralPath $target)) {
    throw "Package directory already exists: $target"
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing isolated .venv Python.' }
if (-not (Test-Path -LiteralPath $spec)) { throw 'Missing Windows spec.' }
foreach ($resource in @('bin\ffmpeg.exe', 'bin\ffprobe.exe', 'icons\mvsp.ico', 'version_info.txt')) {
    $path = Join-Path $PSScriptRoot $resource
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing resource: $path" }
    if ($resource.EndsWith('.exe')) {
        $stream = [IO.File]::OpenRead($path)
        try {
            if ($stream.ReadByte() -ne 77 -or $stream.ReadByte() -ne 90) {
                throw "Resource is not a Windows PE executable: $path"
            }
        } finally { $stream.Dispose() }
    }
}
if ($Stage -eq 'Package') {
    if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Build the package first.' }
    if (-not $SmokeEvidence -or -not (Test-Path -LiteralPath $SmokeEvidence -PathType Leaf)) {
        throw 'Package requires actual frozen GUI smoke evidence.'
    }
    $gate = Get-Content -LiteralPath $SmokeEvidence -Raw | ConvertFrom-Json
    $exeHash = (Get-FileHash -LiteralPath (Join-Path $target 'MultiViewSyncPlayer.exe') -Algorithm SHA256).Hash
    if (-not $gate.passed -or $gate.exe_sha256 -ne $exeHash) {
        throw 'Frozen smoke did not pass for this exact EXE.'
    }
}
New-Item -ItemType Directory -Path $report -Force | Out-Null
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
Start-Transcript -Path (Join-Path $report "06_${Stage}_${runId}.txt")
$previousName = $env:MVSP_DIST_NAME
Push-Location -LiteralPath $repoRoot
try {
    if ($Stage -eq 'Build') {
        $env:MVSP_DIST_NAME = $packageName
        $workRoot = Join-Path $repoRoot "build\windows-v023-test2-$runId"
        if (Test-Path -LiteralPath $workRoot) { throw 'Work directory exists.' }
        & $python -c "import struct, sys; assert sys.platform == 'win32' and struct.calcsize('P') == 8"
        if ($LASTEXITCODE -ne 0) { throw 'Python must be Windows x64.' }
        & $python -m PyInstaller --noconfirm --distpath $distRoot --workpath $workRoot $spec 2>&1 |
            Tee-Object -FilePath (Join-Path $report "06_pyinstaller_$runId.log")
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; outputs retained for inspection.' }
    }
    foreach ($relative in @('MultiViewSyncPlayer.exe', '_internal\bin\ffmpeg.exe', '_internal\bin\ffprobe.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $target $relative) -PathType Leaf)) {
            throw "Incomplete portable package: $relative"
        }
    }
    $files = @(Get-ChildItem -LiteralPath $target -Recurse -File)
    foreach ($required in @('QtWidgets.pyd', 'Qt6Widgets.dll', 'qwindows.dll', 'python312.dll')) {
        if ($required -notin $files.Name) { throw "Missing runtime: $required" }
    }
    foreach ($conflict in @('icuuc.dll', 'icudt78.dll')) {
        if ($conflict -in $files.Name) { throw "Conflicting ICU DLL: $conflict" }
    }
    foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe')) {
        $bundled = Join-Path $target "_internal\bin\$tool"
        $source = Join-Path $PSScriptRoot "bin\$tool"
        if ((Get-FileHash -LiteralPath $bundled).Hash -ne (Get-FileHash -LiteralPath $source).Hash) {
            throw "Bundled tool hash mismatch: $tool"
        }
        & $bundled -version
        if ($LASTEXITCODE -ne 0) { throw "Bundled tool failed: $tool" }
    }
    $files | ForEach-Object {
        [PSCustomObject]@{
            Path = [IO.Path]::GetRelativePath($target, $_.FullName)
            Bytes = $_.Length
            SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } | Export-Csv -LiteralPath (Join-Path $report "06_files_$Stage.csv") -NoTypeInformation -Encoding utf8
    Get-FileHash -LiteralPath (Join-Path $target 'MultiViewSyncPlayer.exe') -Algorithm SHA256 |
        Format-List
    if ($Stage -eq 'Package') {
        Compress-Archive -LiteralPath $target -DestinationPath $zip
        Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Format-List
        Get-Item -LiteralPath $zip | Select-Object FullName, Length | Format-List
    } else {
        Write-Output 'Build complete. Validate the actual frozen EXE before the Package stage.'
    }
} finally {
    $env:MVSP_DIST_NAME = $previousName
    Pop-Location
    Stop-Transcript
}
