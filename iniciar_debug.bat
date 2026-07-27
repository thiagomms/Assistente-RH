@echo off
echo Iniciando Assistente de RH (modo visivel, para depuracao)...
cd /d "%~dp0app"
"%~dp0python\python.exe" -m streamlit run "%~dp0app\dsaprojeto4.py"
echo.
echo O processo foi encerrado. Pressione uma tecla para fechar.
pause >nul
