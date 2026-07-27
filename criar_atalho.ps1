$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path

$driverInstalado = Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server" -ErrorAction SilentlyContinue
if (-not $driverInstalado -and (Test-Path "$raiz\msodbcsql18.msi")) {
    Write-Host "Instalando driver de banco de dados (necessario para a pagina de Vagas)..."
    try {
        Start-Process msiexec.exe -ArgumentList "/i `"$raiz\msodbcsql18.msi`" /quiet /norestart IACCEPTMSODBCSQLLICENSETERMS=YES" -Wait -Verb RunAs
        Write-Host "Driver instalado."
    } catch {
        Write-Host "AVISO: nao foi possivel instalar o driver automaticamente (pode ter sido cancelado o pedido de permissao)."
        Write-Host "A pagina de Vagas nao vai funcionar ate que alguem instale manualmente: $raiz\msodbcsql18.msi"
    }
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$desktop\Assistente de RH.lnk")
$shortcut.TargetPath = "$env:WINDIR\System32\wscript.exe"
$shortcut.Arguments = "//nologo `"$raiz\abrir.vbs`""
$shortcut.WorkingDirectory = $raiz
$shortcut.IconLocation = "$raiz\icone_roxo.ico"
$shortcut.Description = "Assistente de RH - Analise de Curriculos com IA"
$shortcut.Save()

Write-Host ""
Write-Host "================================================"
Write-Host " Pronto! O atalho 'Assistente de RH' foi criado na Area de Trabalho."
Write-Host "================================================"
