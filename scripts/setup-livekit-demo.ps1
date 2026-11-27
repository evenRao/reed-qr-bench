param([switch]$Cloud)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverVersion = '1.13.10'
$serverDirectory = Join-Path $projectRoot ".cache\livekit\$serverVersion"
$serverExecutable = Join-Path $serverDirectory 'livekit-server.exe'
New-Item -ItemType Directory -Path $serverDirectory -Force | Out-Null

if (-not $Cloud -and -not (Test-Path -LiteralPath $serverExecutable)) {
    $assetName = "livekit_${serverVersion}_windows_amd64.zip"
    $releaseBase = "https://github.com/livekit/livekit/releases/download/v$serverVersion"
    $archivePath = Join-Path $serverDirectory $assetName
    $checksumPath = Join-Path $serverDirectory 'checksums.txt'
    Invoke-WebRequest -Uri "$releaseBase/$assetName" -OutFile $archivePath
    Invoke-WebRequest -Uri "$releaseBase/checksums.txt" -OutFile $checksumPath
    $checksumLine = Get-Content -LiteralPath $checksumPath | Where-Object { $_ -match "\s+$([regex]::Escape($assetName))$" } | Select-Object -First 1
    if (-not $checksumLine) { throw 'The official checksum list does not contain the Windows archive.' }
    $expectedChecksum = ($checksumLine -split '\s+')[0]
    $actualChecksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
    if ($actualChecksum -ne $expectedChecksum) { throw 'LiveKit archive checksum mismatch.' }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $serverDirectory -Force
}

if (-not $Cloud) {
    if (-not (Test-Path -LiteralPath $serverExecutable)) { throw 'The LiveKit executable is missing after extraction.' }
    Write-Output "Local LiveKit server ready: $serverExecutable"
}
Write-Output 'The browser SDK is supplied by the locked web/package-lock.json dependencies.'
