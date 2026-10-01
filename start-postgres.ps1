<# Starts the project-local PostgreSQL installation when DATABASE_URL points to localhost. #>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$bin = Join-Path $root ".local\postgresql-17\pgsql\bin"
$data = Join-Path $root ".local\postgresql-data"
$config = Join-Path $root ".env"

if (-not (Test-Path -LiteralPath (Join-Path $bin "pg_ctl.exe")) -or
    -not (Test-Path -LiteralPath $data) -or
    -not (Test-Path -LiteralPath $config)) { return }

$urlLine = Get-Content -LiteralPath $config |
    Where-Object { $_ -match '^DATABASE_URL=' } |
    Select-Object -Last 1
if (-not $urlLine -or $urlLine -notmatch '@(127\.0\.0\.1|localhost):5432/') { return }

& (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p 5432 *> $null
if ($LASTEXITCODE -eq 0) { return }

$log = Join-Path $root ".local\postgresql.log"
& (Join-Path $bin "pg_ctl.exe") -D $data -l $log -o '-h 127.0.0.1 -p 5432' -w start
if ($LASTEXITCODE -ne 0) { throw "Não foi possível iniciar o PostgreSQL local. Consulte $log" }
