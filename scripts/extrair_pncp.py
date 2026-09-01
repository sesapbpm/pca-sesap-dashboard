from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BASE_CNPJ = "08241754"
API = "https://pncp.gov.br/api/pncp/v1"
ANOS = list(range(2022, datetime.now().year + 2))
TIMEOUT = 45


def digitos_cnpj(base12: str) -> str:
    def digito(numeros: str, pesos: list[int]) -> str:
        resto = sum(int(n) * p for n, p in zip(numeros, pesos)) % 11
        return str(0 if resto < 2 else 11 - resto)

    d1 = digito(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digito(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base12 + d1 + d2


def get_json(url: str) -> Any | None:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "SESAP-PCA-Dashboard/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def consultar_resumo(cnpj: str, ano: int) -> tuple[str, int, Any | None]:
    url = f"{API}/orgaos/{cnpj}/pca/{ano}/consolidado"
    return cnpj, ano, get_json(url)


def descobrir_orgaos() -> list[str]:
    candidatos = [digitos_cnpj(f"{BASE_CNPJ}{ordem:04d}") for ordem in range(1, 161)]
    encontrados: set[str] = set()
    anos_referencia = sorted(set([datetime.now().year + 1, datetime.now().year]))
    tarefas = [(cnpj, ano) for cnpj in candidatos for ano in anos_referencia]
    print(f"Verificando {len(candidatos)} estabelecimentos SESAP em {anos_referencia}...")
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(consultar_resumo, cnpj, ano) for cnpj, ano in tarefas]
        for future in as_completed(futures):
            cnpj, _, resumo = future.result()
            if resumo:
                encontrados.add(cnpj)
    return sorted(encontrados)


def normalizar_item(item: dict[str, Any], plano: dict[str, Any]) -> dict[str, Any]:
    valor_total = item.get("valorTotal")
    if valor_total is None:
        valor_total = (item.get("quantidade") or 0) * (item.get("valorUnitario") or 0)
    return {
        "cnpj": plano["cnpj"],
        "razaoSocial": plano.get("razaoSocial"),
        "anoPca": plano["anoPca"],
        "sequencialPca": plano["sequencialPca"],
        "numeroControlePNCP": plano.get("numeroControlePNCP"),
        "codigoUnidade": item.get("codigoUnidade") or plano.get("codigoUnidade"),
        "nomeUnidade": item.get("nomeUnidade") or plano.get("nomeUnidade"),
        "numeroItem": item.get("numeroItem"),
        "categoria": item.get("categoriaItemPcaNome") or "Não informado",
        "tipo": item.get("nomeClassificacao") or "Não informado",
        "descricao": item.get("descricao") or "Sem descrição",
        "classificacaoCodigo": item.get("classificacaoSuperiorCodigo"),
        "classificacaoNome": item.get("classificacaoSuperiorNome") or "Não informado",
        "grupoCodigo": item.get("grupoContratacaoCodigo"),
        "numeroContratacaoFutura": item.get("grupoContratacaoCodigo"),
        "grupoNome": item.get("grupoContratacaoNome") or "Não informado",
        "codigoItem": item.get("codigoItem"),
        "unidadeFornecimento": item.get("unidadeFornecimento"),
        "quantidade": item.get("quantidade") or 0,
        "valorUnitario": item.get("valorUnitario") or 0,
        "valorTotal": valor_total or 0,
        "valorOrcamentoExercicio": item.get("valorOrcamentoExercicio") or 0,
        "dataDesejada": item.get("dataDesejada"),
        "dataPublicacao": item.get("dataPublicacaoPncp"),
        "dataAtualizacao": item.get("dataAtualizacao"),
        "unidadeRequisitante": item.get("unidadeRequisitante"),
        "catalogo": item.get("nomeCatalogo"),
    }


def extrair() -> None:
    inicio = time.time()
    DATA_DIR.mkdir(exist_ok=True)
    cnpjs = descobrir_orgaos()
    if not cnpjs:
        raise RuntimeError("Nenhum PCA da rede SESAP foi encontrado no PNCP.")
    print(f"Órgãos com PCA: {len(cnpjs)}")

    resumos: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(consultar_resumo, cnpj, ano) for cnpj in cnpjs for ano in ANOS]
        for future in as_completed(futures):
            cnpj, ano, resumo = future.result()
            if resumo:
                print(f"  {cnpj} / {ano}: {resumo.get('quantidade', 0)} itens")
                unidades = get_json(f"{API}/orgaos/{cnpj}/pca/{ano}/consolidado/unidades") or []
                for unidade in unidades:
                    resumos.append(unidade)

    itens: list[dict[str, Any]] = []
    for plano in sorted(resumos, key=lambda p: (p["anoPca"], p["cnpj"], p["sequencialPca"])):
        url = (
            f"{API}/orgaos/{plano['cnpj']}/pca/"
            f"{plano['anoPca']}/{plano['sequencialPca']}/itens"
        )
        dados = get_json(url) or []
        itens.extend(normalizar_item(item, plano) for item in dados)

    itens.sort(key=lambda i: (i["anoPca"], i["nomeUnidade"] or "", i["numeroItem"] or 0))
    campos = list(itens[0].keys()) if itens else []
    with (DATA_DIR / "pca_sesap.csv").open("w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=campos)
        writer.writeheader()
        writer.writerows(itens)

    payload = {
        "metadata": {
            "fonte": "Portal Nacional de Contratações Públicas - PNCP",
            "api": API,
            "extraidoEm": datetime.now().astimezone().isoformat(timespec="seconds"),
            "anosConsultados": ANOS,
            "anosDisponiveis": sorted({i["anoPca"] for i in itens}),
            "quantidadeItens": len(itens),
            "quantidadeOrgaos": len({i["cnpj"] for i in itens}),
            "cnpjs": cnpjs,
        },
        "planos": resumos,
        "itens": itens,
    }
    with (DATA_DIR / "pca_sesap.json").open("w", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False, separators=(",", ":"))
    print(f"Concluído: {len(itens)} itens em {time.time() - inicio:.1f}s")


if __name__ == "__main__":
    try:
        extrair()
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise
