[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectName = "kavach-saathi"

Set-Location $projectRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

Write-Host "Starting existing Kavach Saathi images (no build)..." -ForegroundColor Cyan
Invoke-Checked {
    docker compose -p $projectName up -d --no-build postgres redis backend frontend
} "Could not start the existing Docker images. Run a normal build once if an image is missing."

$backendId = (docker compose -p $projectName ps -q backend).Trim()
$frontendId = (docker compose -p $projectName ps -q frontend).Trim()
if (-not $backendId -or -not $frontendId) {
    throw "Backend or frontend container is unavailable. Check Docker Desktop and docker compose ps."
}

Write-Host "Copying backend source into the existing container..." -ForegroundColor Cyan
Invoke-Checked { docker cp (Join-Path $projectRoot "src\.") "${backendId}:/app/src" } "Could not copy backend source."
Invoke-Checked { docker cp (Join-Path $projectRoot "data\.") "${backendId}:/app/data" } "Could not copy backend data."
Invoke-Checked { docker cp (Join-Path $projectRoot "migrations\.") "${backendId}:/app/migrations" } "Could not copy migrations."
Invoke-Checked { docker cp (Join-Path $projectRoot "scripts\.") "${backendId}:/app/scripts" } "Could not copy backend scripts."
Invoke-Checked { docker cp (Join-Path $projectRoot "alembic.ini") "${backendId}:/app/alembic.ini" } "Could not copy Alembic configuration."

Write-Host "Copying frontend source into the existing container..." -ForegroundColor Cyan
Invoke-Checked { docker cp (Join-Path $projectRoot "web\app\.") "${frontendId}:/app/app" } "Could not copy frontend app files."
Invoke-Checked { docker cp (Join-Path $projectRoot "web\components\.") "${frontendId}:/app/components" } "Could not copy frontend components."
Invoke-Checked { docker cp (Join-Path $projectRoot "web\lib\.") "${frontendId}:/app/lib" } "Could not copy frontend library files."
Invoke-Checked { docker cp (Join-Path $projectRoot "web\next.config.mjs") "${frontendId}:/app/next.config.mjs" } "Could not copy Next.js configuration."

Write-Host "Restarting application containers..." -ForegroundColor Cyan
Invoke-Checked { docker restart $backendId $frontendId | Out-Null } "Could not restart the application containers."

$deadline = (Get-Date).AddMinutes(3)
do {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5
        if ($health.status -eq "ok") {
            Write-Host "Updated site is ready: http://localhost:3000" -ForegroundColor Green
            Write-Host "Backend health is OK: http://localhost:8000/health" -ForegroundColor Green
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 3
    }
} while ((Get-Date) -lt $deadline)

Write-Warning "Containers restarted, but the backend is still warming up. Check: docker compose -p $projectName logs backend --tail 100"
exit 1
