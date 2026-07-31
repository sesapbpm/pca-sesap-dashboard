@echo off
cd /d "%~dp0"
python scripts\extrair_pncp.py
python scripts\extrair_ciclo_compras.py
pause
