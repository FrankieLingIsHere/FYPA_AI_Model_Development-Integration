param(
    [string]$BaseUrl = "https://fypaaimodeldevelopment-integration-production.up.railway.app",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$pythonExe = Join-Path $repoRoot ".venv/Scripts/python.exe"
$cloudHealthScript = Join-Path $scriptDir "deployed_runtime_cloud_health_check.py"
$nlpContractScript = Join-Path $scriptDir "deployed_runtime_nlp_metrics_contract_test.py"

if (-not (Test-Path $pythonExe)) {
    Write-Output ("FAIL: python executable not found at " + $pythonExe)
    exit 2
}
if (-not (Test-Path $cloudHealthScript)) {
    Write-Output ("FAIL: script not found: " + $cloudHealthScript)
    exit 2
}
if (-not (Test-Path $nlpContractScript)) {
    Write-Output ("FAIL: script not found: " + $nlpContractScript)
    exit 2
}

$env:LUNA_BASE_URL = $BaseUrl.TrimEnd('/')
if ($Strict) {
    $env:LUNA_RUNTIME_HEALTH_STRICT = "1"
    $env:LUNA_RUNTIME_NLP_CONTRACT_NON_BLOCKING = "0"
} else {
    $env:LUNA_RUNTIME_HEALTH_STRICT = "0"
    $env:LUNA_RUNTIME_NLP_CONTRACT_NON_BLOCKING = "0"
}

Write-Output ("INFO: running deployed runtime health checks against " + $env:LUNA_BASE_URL)

$overallCode = 0

& $pythonExe $cloudHealthScript
$cloudCode = $LASTEXITCODE
if ($cloudCode -ne 0 -and $overallCode -eq 0) {
    $overallCode = $cloudCode
}

& $pythonExe $nlpContractScript
$contractCode = $LASTEXITCODE
if ($contractCode -ne 0 -and $overallCode -eq 0) {
    $overallCode = $contractCode
}

Write-Output ("RUNTIME_HEALTH_EXITCODE:" + $overallCode)
exit $overallCode
