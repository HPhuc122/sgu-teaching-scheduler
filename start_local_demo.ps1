param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8010
)

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$manage = Join-Path $projectRoot 'backend\manage.py'
$demoDatabase = Join-Path $projectRoot 'outputs\sgu_public_demo_DCT\demo.sqlite3'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Khong tim thay Python trong .venv: $python"
}
if (-not (Test-Path -LiteralPath $demoDatabase)) {
    throw "Khong tim thay CSDL demo: $demoDatabase"
}

$env:UCTP_DEBUG = '1'
$env:UCTP_SQLITE_PATH = $demoDatabase
$env:PYTHONIOENCODING = 'utf-8'

& $python $manage runserver "127.0.0.1:$Port" --noreload
