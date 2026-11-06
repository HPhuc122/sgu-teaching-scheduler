param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8010
)

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$manage = Join-Path $projectRoot 'backend\manage.py'
$database = Join-Path $projectRoot 'outputs\sgu_public_demo_DCT\demo.sqlite3'
$logs = Join-Path $projectRoot 'outputs\bao_cao_20_mau\server'
if (-not (Test-Path -LiteralPath $database)) { throw "Khong tim thay CSDL demo: $database" }
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$env:UCTP_DEBUG = '1'
$env:UCTP_SQLITE_PATH = $database
$env:PYTHONIOENCODING = 'utf-8'

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "Cong $Port dang duoc su dung. Kiem tra may chu hien tai truoc khi khoi dong ban bao cao."
}
$worker = Start-Process -FilePath $python -ArgumentList @('-u', $manage, 'process_auto_schedule') `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'worker_stdout.log') -RedirectStandardError (Join-Path $logs 'worker_stderr.log')
@{ launcher_pid = $PID; worker_pid = $worker.Id; port = $Port; database = $database } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logs 'processes.json') -Encoding utf8
Write-Output "Web: http://127.0.0.1:$Port/admin/auto-schedule/"
Write-Output "Da khoi dong ca web va worker xep lich. Nhat ky: $logs"
Write-Output "Giu cua so lenh nay mo trong khi trinh dien."
try {
    & $python -u $manage runserver "127.0.0.1:$Port" --noreload
}
finally {
    # The venv launcher can have its own Python child on Windows.
    & taskkill /PID $worker.Id /T /F 2>$null | Out-Null
}
