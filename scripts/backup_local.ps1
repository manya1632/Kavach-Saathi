[CmdletBinding()]
param(
    [string]$Destination = "backups"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = Join-Path $projectRoot $Destination
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $backupRoot $stamp

New-Item -ItemType Directory -Path $target -Force | Out-Null
Set-Location $projectRoot

$postgresId = (docker compose ps -q postgres).Trim()
$redisId = (docker compose ps -q redis).Trim()
if (-not $postgresId -or -not $redisId) {
    throw "PostgreSQL and Redis containers must be running before a backup can be created."
}

docker exec $postgresId sh -c "pg_dump -U kavach -d kavach_saathi --format=custom --file=/tmp/kavach-saathi.dump"
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed." }
docker cp "${postgresId}:/tmp/kavach-saathi.dump" (Join-Path $target "postgres.dump")
docker exec $postgresId rm -f /tmp/kavach-saathi.dump

docker exec $redisId redis-cli BGSAVE | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Redis backup failed." }
$deadline = (Get-Date).AddMinutes(1)
do {
    $status = docker exec $redisId redis-cli LASTSAVE
    if ($LASTEXITCODE -eq 0 -and $status) { break }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)
docker cp "${redisId}:/data/dump.rdb" (Join-Path $target "redis.rdb")

$manifest = @{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    postgres = "postgres.dump"
    redis = "redis.rdb"
    restore_test_required = $true
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $target "manifest.json") -Value $manifest -Encoding UTF8
Write-Host "Backup created at $target" -ForegroundColor Green
