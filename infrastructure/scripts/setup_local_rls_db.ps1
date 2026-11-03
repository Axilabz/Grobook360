# LOCAL ONLY. Creates the throwaway Phase 1C database + roles on the local Postgres 16 (port 5433).
# You will be prompted ONCE for the local `postgres` superuser password. Nothing is sent anywhere.
#   powershell -ExecutionPolicy Bypass -File infrastructure\scripts\setup_local_rls_db.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$cfg = @{}
Get-Content "$root\backend\.env.rls.local" | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k,$v = $_ -split '=',2; $cfg[$k] = $v }
$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
$common = @("-h","localhost","-p","5433","-U","postgres","-v","ON_ERROR_STOP=1")
& $psql @common -d postgres -v "owner_pw=$($cfg.RLS_OWNER_PW)" -f "$root\infrastructure\scripts\local_rls_database.sql"
& $psql @common -d saas_rls_dev -v "owner_role=grobook_owner" -v "app_pw=$($cfg.RLS_APP_PW)" -f "$root\infrastructure\scripts\rls_bootstrap_roles.sql"
Write-Host "Done. Tell Claude the script finished."
