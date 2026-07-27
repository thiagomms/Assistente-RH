$raiz   = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $raiz "app"
$pyExe  = Join-Path $raiz "python\python.exe"
$appPy  = Join-Path $appDir "dsaprojeto4.py"
$log    = Join-Path $raiz "log.txt"
$porta  = 8501

$rodando = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$porta/_stcore/health" -UseBasicParsing -TimeoutSec 2
    if ($resp.StatusCode -eq 200) { $rodando = $true }
} catch {}

if (-not $rodando) {
    # Encerra qualquer instancia antiga/travada deste mesmo app antes de subir uma nova
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$appPy*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    Start-Sleep -Milliseconds 800

    Set-Location $appDir
    Start-Process -FilePath $pyExe `
        -ArgumentList @("-m", "streamlit", "run", "`"$appPy`"", "--server.port", $porta, "--server.headless", "true", "--browser.gatherUsageStats", "false") `
        -RedirectStandardOutput $log `
        -WindowStyle Hidden

    Start-Sleep -Seconds 4
}

$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" }

if (Test-Path $edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=http://localhost:$porta"
} else {
    Start-Process "http://localhost:$porta"
}
