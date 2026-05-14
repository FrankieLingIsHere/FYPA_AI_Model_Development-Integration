$ErrorActionPreference = 'Stop'

$root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$serverPath = Join-Path $PSScriptRoot 'mira-simplerest-server.js'
$port = 47823
$logDir = Join-Path $root 'output\mira-botium'
$stdout = Join-Path $logDir 'server.out.log'
$stderr = Join-Path $logDir 'server.err.log'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$server = Start-Process -WindowStyle Hidden -PassThru -FilePath 'node' -ArgumentList @("`"$serverPath`"") -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    $ready = $false
    for ($i = 0; $i -lt 30; $i += 1) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }

    if (-not $ready) {
        throw "Mira Botium wrapper did not become ready on port $port"
    }

    Push-Location $PSScriptRoot
    try {
        npx --yes botium-cli run spec --convos convo --timeout 20
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
