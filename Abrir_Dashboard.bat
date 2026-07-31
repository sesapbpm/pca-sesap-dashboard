@echo off
cd /d "%~dp0"
title Dashboard PCA SESAP - Servidor local
echo Iniciando o Dashboard PCA SESAP...
echo Mantenha esta janela aberta durante o uso.
python servidor.py
echo.
echo O servidor foi encerrado. Pressione uma tecla para fechar.
pause
