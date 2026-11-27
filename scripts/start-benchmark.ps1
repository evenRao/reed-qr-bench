param([int]$Port = 8765, [switch]$SetupLiveKit, [switch]$UseBuiltUI)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if ($SetupLiveKit) {
        & (Join-Path $PSScriptRoot 'setup-livekit-demo.ps1')
    }
    uv sync --locked --no-dev --extra voice
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the benchmark environment.' }
    if ($UseBuiltUI) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\index.html'))) {
            throw 'The prebuilt browser UI is missing. Run without -UseBuiltUI to build it.'
        }
    } else {
        $lockPath = Join-Path $projectRoot 'web\package-lock.json'
        $stampPath = Join-Path $projectRoot '.cache\bench-ui-lock.sha256'
        $lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash
        $installedHash = if (Test-Path -LiteralPath $stampPath) { (Get-Content -LiteralPath $stampPath -Raw).Trim() } else { '' }
        if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'web\node_modules')) -or $installedHash -ne $lockHash) {
            npm ci --prefix web --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Could not install the browser dependencies.' }
            New-Item -ItemType Directory -Path (Join-Path $projectRoot '.cache') -Force | Out-Null
            $lockHash | Set-Content -LiteralPath $stampPath -Encoding ascii
        }
        npm --prefix web run build
        if ($LASTEXITCODE -ne 0) { throw 'The TypeScript UI build failed.' }
    }
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -u -m reed_bench --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'The benchmark app exited with an error.' }
} finally {
    Pop-Location
}
