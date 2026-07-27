@echo off
title Configurando Assistente de RH...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0criar_atalho.ps1"
echo.
echo Pressione uma tecla para fechar esta janela.
pause >nul
