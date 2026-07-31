from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def carregar(nome: str) -> dict:
    caminho = ROOT / "data" / nome
    if not caminho.exists() or caminho.stat().st_size < 100:
        raise RuntimeError(f"Arquivo ausente ou vazio: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


pca = carregar("pca_sesap.json")
ciclo = carregar("ciclo_compras_sesap.json")

itens = pca.get("itens") or []
vinculos = ciclo.get("vinculos") or []
compras = ciclo.get("compras") or []

if not itens:
    raise RuntimeError("A atualização do PCA retornou zero itens.")
if len(vinculos) != len(itens):
    raise RuntimeError(f"Quantidade de vínculos ({len(vinculos)}) diferente dos itens ({len(itens)}).")
if "metadata" not in pca or "metadata" not in ciclo:
    raise RuntimeError("Metadados de atualização ausentes.")

print(f"Validação concluída: {len(itens)} itens, {len(compras)} compras e {len(vinculos)} vínculos.")
