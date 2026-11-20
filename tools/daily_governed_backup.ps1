<#
  The daily governed generation (Layer-2 + object set, recorded in the cutover ledger), with NO prompts once the
  secrets are stored: it reads D:\SGAA_CUTOVER\secrets (Windows DPAPI, this Windows user on this PC only; written by
  gf1_4fc8222\finish_onedrive_fix.ps1, store_drive_read_secrets.ps1, or by this script the first time, only after
  they were proven).  Nothing is deployed, authorized or promoted.

  Documents released from Supabase staging are backed up from their verified Google Drive copy.  That read needs the
  production TOKEN_ENCRYPTION_KEY and the Google application credentials (owner decision 2026-10-18, a recorded
  deviation from runbook section 0 "Secrets"); with them the object backup may refresh the Google access token and
  store the refreshed token in PROD, exactly as the hosted application does.

  Every governed generation takes the documents too: once an object set is registered, a database-only governed
  run is refused (GENERATION_NOT_THIS_RUNS) after it has already registered its database set, so there is no
  database-only fallback here.  Exit code: 0 generation recorded | 1 nothing recorded (the log names why and the
  cadence deadline).  A run the log refuses continues in daily_governed_backup.fallback-*.log beside it.

  Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File D:\SGAA_CUTOVER\daily_governed_backup.ps1
#>
$ErrorActionPreference = 'Continue'
$Ref        = 'uckadhcwfknklmdktuyi'
$Pooler     = 'aws-0-us-east-1.pooler.supabase.com'
$Bucket     = 'sgaa-documentos'
$Wt         = 'D:\SGAA_wt\gf1_4087eaf'
$Py         = 'D:\SGAA_venv\mp3_py312_b\Scripts\python.exe'
$Ledger     = 'D:\SGAA_CUTOVER\ledger'
$Log        = 'D:\SGAA_CUTOVER\daily_governed_backup.log'
$RollRoot   = 'D:\SGAA_CUSTODY\mp3-cutover\rolling'
$RollOff    = 'D:\SGAA_CUTOVER\rolling-off'
$PgBin      = 'D:\SGAA_PG\pg17_extract\pgsql\bin'
$Secrets    = 'D:\SGAA_CUTOVER\secrets'
$DbFile     = Join-Path $Secrets 'prod_db_password.dpapi'
$KeyFile    = Join-Path $Secrets 'prod_storage_key.dpapi'
$DriveFiles = @{ TOKEN_ENCRYPTION_KEY = (Join-Path $Secrets 'prod_token_encryption_key.dpapi');
                 GOOGLE_CLIENT_ID     = (Join-Path $Secrets 'prod_google_client_id.dpapi');
                 GOOGLE_CLIENT_SECRET = (Join-Path $Secrets 'prod_google_client_secret.dpapi') }
$StoreProbe = 'D:\SGAA_CUTOVER\gf1_4fc8222\storage_key_probe.py'
$DriveProbe = 'D:\SGAA_CUTOVER\drive_read_key_probe.py'
$Names      = @('PGPASSWORD','PGPASSFILE','DATABASE_URL','APP_ENV','SGAA_RUNTIME','TRUST_PROXY_XFF','SUPABASE_URL',
                'SGAA_STORAGE_BUCKET','SGAA_PG_BIN_DIR','APP_SECRET_KEY','TOKEN_ENCRYPTION_KEY','SGAA_ADMISSION',
                'SGAA_OPENING_REFERENCE','APP_PUBLIC_BASE_URL','SUPABASE_SECRET_KEY','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET')
$ExitCode   = 1
$LogFallback = $null

# Windows PowerShell 5.1 Add-Content refuses to append while any process holds the file open (a tail, Get-Content
# -Wait, an editor, a scanner) and, under 'Continue', loses the line without a trace.  So a line is appended with
# read/write/delete sharing, which no reader that shares writes refuses, and retried for 5 s; if the log still
# refuses (a handle that denies writes), the rest of the run goes to a fallback file beside it, named on the console
# and, once the log takes writes again, at its end.  When no file takes a line Write-Log throws LOG_UNWRITABLE,
# which stops a run before its generation (a governed generation does not start without a record of its run); the
# lines written once the outcome is decided pass -NoThrow, so a log failure never changes what the exit code reports.
function Add-LogLine([string]$Path, [string]$Text) {
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text + "`r`n")
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write,
                ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush() } finally { $stream.Dispose() }
            return $true
        } catch { Start-Sleep -Milliseconds 250 }  # a refused line is reported to the caller, which decides
    }
    return $false
}
function Write-Log([string]$Text, [switch]$NoThrow) {
    Write-Host $Text
    if (-not $script:LogFallback) {
        if (Add-LogLine $Log $Text) { return }
        $script:LogFallback = '{0}.fallback-{1}-{2}.log' -f ($Log -replace '\.log$', ''), (Get-Date -Format 'yyyyMMddHHmmss'), $PID
        Write-Host ("== WARNING: {0} refused writes; this run continues its log in {1}" -f $Log, $script:LogFallback)
        [void](Add-LogLine $script:LogFallback ("== {0} refused writes from here on; this file continues it" -f $Log))
    }
    if (Add-LogLine $script:LogFallback $Text) { return }
    if (-not $NoThrow) { throw 'LOG_UNWRITABLE' }
}
function Read-Secret([string]$File, [string]$Prompt) {
    if (Test-Path $File) { return @{ Secure = (Get-Content $File | ConvertTo-SecureString); Stored = $true } }
    return @{ Secure = (Read-Host -AsSecureString $Prompt); Stored = $false }
}
function Save-Secret($Secret, [string]$File) {
    if ($Secret.Stored) { return }
    New-Item -ItemType Directory -Force -Path $Secrets | Out-Null
    $Secret.Secure | ConvertFrom-SecureString | Set-Content -Path $File -Encoding ASCII
}
function Unprotect([string]$File) {
    [System.Net.NetworkCredential]::new('', (Get-Content $File | ConvertTo-SecureString)).Password.Trim()
}
function Invoke-Generation([bool]$Objects, [string]$Label) {
    $cli = @('tools\ops_backup.py', '--root', $RollRoot, '--off-platform', $RollOff, '--generations', '3',
             '--label', $Label, '--ledger-dir', $Ledger)
    if ($Objects) { $cli += '--objects' }
    $out = & $Py @cli 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $out) { Write-Log "$line" -NoThrow }
    return $code
}
function Cadence-Deadline {
    # the newest recorded generation + the 24 h cadence with its tolerance (x 1.5), value-free
    $rows = @(Get-Content $Ledger\ledger.jsonl | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    $sets = @($rows | Where-Object { $_.type -eq 'backup' -and $_.generation_at })
    if ($sets.Count -eq 0) { return 'unknown' }
    $newest = ($sets | ForEach-Object { [datetime]::Parse($_.generation_at).ToUniversalTime() } | Sort-Object)[-1]
    return $newest.AddHours(36).ToString("yyyy-MM-ddTHH:mm:ssZ")
}

Push-Location $Wt
try {
    Write-Log ("#### daily governed generation start {0}" -f (Get-Date -Format s))
    if (Test-Path Env:DATABASE_URL) { Write-Log 'REFUSED: DATABASE_URL is already set in this window'; throw 'PRECONDITION' }
    if (& git -C $Wt status --porcelain) { Write-Log 'REFUSED: the worktree is not clean'; throw 'PRECONDITION' }
    $env:PYTHONDONTWRITEBYTECODE = '1'; $env:TEMP = 'D:\SGAA_tmp'; $env:TMP = 'D:\SGAA_tmp'
    $status = (& $Py tools\cutover_ledger.py status --ledger-dir $Ledger) | ConvertFrom-Json
    if ($status.unresolved_operation -or $status.chain -ne 'OK') { Write-Log 'REFUSED: the ledger is not clean'; throw 'PRECONDITION' }

    $drive = @($DriveFiles.Values | Where-Object { -not (Test-Path $_) }).Count -eq 0
    $env:APP_SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    if ($drive) {
        foreach ($name in $DriveFiles.Keys) { Set-Item "Env:$name" (Unprotect $DriveFiles[$name]) }
    } else {  # throwaway: the database-only generation never decrypts a stored token
        $env:TOKEN_ENCRYPTION_KEY = (& $Py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
    }
    $env:APP_ENV = 'production'; $env:SGAA_RUNTIME = 'hosted'; $env:TRUST_PROXY_XFF = '1'
    $env:SGAA_ADMISSION = 'open'; $env:SGAA_OPENING_REFERENCE = ('5' * 64)
    $env:APP_PUBLIC_BASE_URL = 'https://sgaa.example.test'
    $env:SUPABASE_URL = "https://${Ref}.supabase.co"; $env:SGAA_STORAGE_BUCKET = $Bucket
    $env:SGAA_PG_BIN_DIR = $PgBin
    $env:PGPASSFILE = 'D:\SGAA_CUTOVER\no-password-file'
    $db = Read-Secret $DbFile 'PROD database password (postgres) -- last time, it will be remembered'
    $env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $db.Secure).Password
    $key = Read-Secret $KeyFile 'PROD storage key (legacy service_role eyJ... or sb_secret_) -- last time, it will be remembered'
    $env:SUPABASE_SECRET_KEY = [System.Net.NetworkCredential]::new('', $key.Secure).Password.Trim()
    $env:DATABASE_URL = "postgresql://postgres.${Ref}@${Pooler}:5432/postgres?sslmode=verify-full"

    $result = $null; $reason = $null
    $probe = ((& $Py $StoreProbe 2>&1) | Select-Object -Last 1) -as [string]
    Write-Log ("storage key probe: {0}" -f $probe)
    if (-not $probe -or -not $probe.StartsWith('KEY_OK')) {
        # never delete a stored key here: a transient failure must not strand the unattended task at a prompt
        $reason = 'the storage key was not accepted'
    } else {
        Save-Secret $key $KeyFile
        if (-not $drive) {
            $reason = 'the drive-read secrets are not stored (run store_drive_read_secrets.ps1)'
        } else {
            $dprobe = ((& $Py $DriveProbe 2>&1) | Select-Object -Last 1) -as [string]
            Write-Log ("drive read probe: {0}" -f $dprobe)
            if (-not $dprobe -or -not $dprobe.StartsWith('KEY_OK') -or $dprobe -notmatch 'app_credentials=CONFIGURED') {
                $reason = 'the drive-read secrets were not accepted'
            } else {
                Write-Log ("== full generation (database + documents) {0}" -f (Get-Date -Format s))
                $code = Invoke-Generation $true 'daily'
                if ($code -eq 0) { $result = 'FULL' } else { $reason = "the documents generation failed (exit $code)" }
            }
        }
    }
    if (-not $result) {
        Write-Log ("NO GENERATION RECORDED: {0}. Cadence deadline {1}." -f $reason, (Cadence-Deadline)) -NoThrow
        throw 'GENERATION'
    }
    Save-Secret $db $DbFile
    $ExitCode = 0
    Write-Log ("#### RESULT: generation recorded (database + documents). Next cadence deadline {0}." -f (Cadence-Deadline)) -NoThrow
}
catch { Write-Log ("#### stopped: {0}" -f $_.Exception.Message) -NoThrow }
finally {
    foreach ($name in $Names) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    Pop-Location
    if ($LogFallback -and (Test-Path -LiteralPath $LogFallback)) {
        [void](Add-LogLine $Log ("#### this run's log continued in {0}" -f $LogFallback))
    }
}
exit $ExitCode
