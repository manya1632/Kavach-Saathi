[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedBackup = (Resolve-Path -LiteralPath $BackupDirectory).Path
$postgresBackup = Join-Path $resolvedBackup "postgres.dump"
$redisBackup = Join-Path $resolvedBackup "redis.rdb"
if (-not (Test-Path -LiteralPath $postgresBackup) -or -not (Test-Path -LiteralPath $redisBackup)) {
    throw "The backup directory must contain postgres.dump and redis.rdb."
}

Set-Location $projectRoot
$postgresId = (docker compose ps -q postgres).Trim()
$redisId = (docker compose ps -q redis).Trim()
if (-not $postgresId -or -not $redisId) {
    throw "PostgreSQL and Redis containers must be running for verification."
}

$verificationDb = "kavach_restore_check_$(Get-Date -Format 'yyyyMMddHHmmss')"
if ($verificationDb -notmatch '^kavach_restore_check_[0-9]{14}$') {
    throw "Refusing to use an unexpected verification database name."
}

try {
    docker cp $postgresBackup "${postgresId}:/tmp/restore-check.dump"
    docker exec $postgresId createdb -U kavach $verificationDb
    if ($LASTEXITCODE -ne 0) { throw "Could not create the temporary verification database." }
    docker exec $postgresId pg_restore -U kavach -d $verificationDb --exit-on-error /tmp/restore-check.dump
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore verification failed." }
    $tableCount = docker exec $postgresId psql -U kavach -d $verificationDb -Atc "select count(*) from information_schema.tables where table_schema='public';"
    if ([int]$tableCount -lt 1) { throw "The restored PostgreSQL backup contains no public tables." }

    docker cp $redisBackup "${redisId}:/tmp/restore-check.rdb"
    docker exec $redisId redis-check-rdb /tmp/restore-check.rdb | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Redis backup verification failed." }
    Write-Host "Backup restore verification passed ($tableCount PostgreSQL tables)." -ForegroundColor Green
}
finally {
    docker exec $postgresId dropdb -U kavach --if-exists $verificationDb | Out-Null
    docker exec $postgresId rm -f /tmp/restore-check.dump | Out-Null
    docker exec $redisId rm -f /tmp/restore-check.rdb | Out-Null
}
