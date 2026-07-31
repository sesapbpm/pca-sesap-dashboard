$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python scripts/extrair_pncp.py
python scripts/extrair_ciclo_compras.py
Write-Host ""
Write-Host "Base do PNCP atualizada com sucesso." -ForegroundColor Green
