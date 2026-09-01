from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COMPRAS_API = "https://dadosabertos.compras.gov.br"
PNCP_API = "https://pncp.gov.br/api/consulta/v1"
MODALIDADES = [3, 5, 6, 7, 12]
TIMEOUT = 30


def get_json(url: str, retries: int = 5) -> Any | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SESAP-Ciclo-Compras/2.0"})
    for tentativa in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return None
            if exc.code == 429:
                espera = int(exc.headers.get("Retry-After") or (4 + tentativa * 3))
                time.sleep(min(espera, 30))
                continue
            if tentativa == retries:
                raise
        except Exception:
            if tentativa == retries:
                raise
        time.sleep(1.5 * (tentativa + 1))
    return None


def normalizar(texto: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def periodos() -> list[tuple[str, str]]:
    fim = date.today()
    saida = []
    for ano in range(2024, fim.year + 1):
        final = fim if ano == fim.year else date(ano, 12, 31)
        saida.append((f"{ano}-01-01", final.isoformat()))
    return saida


def paginar(url: str, params: dict[str, Any], tamanho: int = 500) -> list[dict[str, Any]]:
    pagina, dados = 1, []
    while True:
        query = urllib.parse.urlencode({**params, "pagina": pagina, "tamanhoPagina": tamanho})
        resposta = get_json(f"{url}?{query}")
        if not resposta:
            break
        lote = resposta.get("resultado") or resposta.get("data") or []
        dados.extend(lote)
        total_paginas = int(resposta.get("totalPaginas") or 1)
        if pagina >= total_paginas:
            break
        pagina += 1
    return dados


def buscar_pgc(plano: dict[str, Any]) -> list[dict[str, Any]]:
    return paginar(
        f"{COMPRAS_API}/modulo-pgc/1_consultarPgcDetalhe",
        {"orgao": plano["cnpj"], "anoPcaProjetoCompra": plano["anoPca"], "codigoUasg": plano["codigoUnidade"]},
    )


def buscar_compras(tarefa: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    cnpj, inicio, fim, modalidade = tarefa
    return paginar(
        f"{COMPRAS_API}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133",
        {"orgaoEntidadeCnpj": cnpj, "dataPublicacaoPncpInicial": inicio, "dataPublicacaoPncpFinal": fim, "codigoModalidade": modalidade},
    )


def buscar_contratos_api(tarefa: tuple[str, str, str]) -> list[dict[str, Any]]:
    uasg, inicio, fim = tarefa
    return paginar(
        f"{COMPRAS_API}/modulo-contratos/1_consultarContratos",
        {"codigoUnidadeGestora": uasg, "dataVigenciaInicialMin": inicio, "dataVigenciaInicialMax": fim},
    )


def detalhes_compra(compra: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cnpj = compra["orgaoEntidadeCnpj"]
    ano = int(compra["anoCompraPncp"])
    seq = int(compra["sequencialCompraPncp"])
    itens_url = f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{seq}/itens?tamanhoPagina=500&pagina=1"
    contratos_url = f"{PNCP_API}/orgaos/{cnpj}/contratos/contratacao/{ano}/{seq}"
    atas_url = f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{seq}/atas"
    itens_raw = get_json(itens_url, retries=1) or []
    if isinstance(itens_raw, dict):
        itens_raw = itens_raw.get("itens") or itens_raw.get("data") or []
    contratos_raw = get_json(contratos_url, retries=1) or []
    if isinstance(contratos_raw, dict):
        contratos_raw = contratos_raw.get("data") or [contratos_raw]
    atas_raw = get_json(atas_url, retries=1) or [] if compra.get("srp") else []
    if isinstance(atas_raw, dict):
        atas_raw = atas_raw.get("data") or atas_raw.get("atas") or [atas_raw]
    return compra["idCompra"], itens_raw, contratos_raw, atas_raw


def status_contrato(contrato: dict[str, Any]) -> str:
    hoje = date.today().isoformat()
    inicio = str(contrato.get("dataVigenciaInicio") or contrato.get("dataVigenciaInicial") or "")[:10]
    fim = str(contrato.get("dataVigenciaFim") or contrato.get("dataVigenciaFinal") or "")[:10]
    if contrato.get("contratoExcluido") or contrato.get("excluido"):
        return "Excluído"
    if inicio and hoje < inicio:
        return "A iniciar"
    if fim and hoje > fim:
        return "Encerrado"
    if inicio and fim:
        return "Vigente"
    return "Sem vigência informada"


def executar() -> None:
    inicio_exec = time.time()
    base = json.loads((DATA / "pca_sesap.json").read_text(encoding="utf-8"))
    planos_unicos = list({(p["cnpj"], p["anoPca"], p["codigoUnidade"]): p for p in base["planos"]}.values())
    print(f"Consultando PGC para {len(planos_unicos)} planos...")
    pgc: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(buscar_pgc, p) for p in planos_unicos]
        for future in as_completed(futures):
            try:
                pgc.extend(future.result())
            except Exception as exc:
                print(f"Aviso PGC: {exc}")

    cnpjs = sorted({p["cnpj"] for p in planos_unicos})
    tarefas = [(cnpj, ini, fim, mod) for cnpj in cnpjs for ini, fim in periodos() for mod in MODALIDADES]
    print(f"Consultando {len(tarefas)} combinações de compras...")
    compras: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(buscar_compras, t) for t in tarefas]
        for future in as_completed(futures):
            try:
                compras.extend(future.result())
            except Exception as exc:
                print(f"Aviso compras: {exc}")
    compras = list({c["idCompra"]: c for c in compras}.values())
    codigos_futuros = set()
    for item_pca in base["itens"]:
        match = re.fullmatch(r"(\d+)-(\d+)/(\d{4})", str(item_pca.get("numeroContratacaoFutura") or item_pca.get("grupoCodigo") or ""))
        if match:
            uasg, numero, ano = match.groups()
            codigos_futuros.add((item_pca["cnpj"], uasg, int(ano), numero.lstrip("0") or "0"))
    compras_detalhar = [c for c in compras if (str(c.get("orgaoEntidadeCnpj")), str(c.get("unidadeOrgaoCodigoUnidade")), int(c.get("anoCompraPncp") or 0), str(c.get("numeroCompra") or "").lstrip("0") or "0") in codigos_futuros]
    print(f"Compras localizadas: {len(compras)}. Consultando detalhes de {len(compras_detalhar)} vínculos oficiais...")

    compra_itens: dict[str, list[dict[str, Any]]] = {}
    contratos: list[dict[str, Any]] = []
    atas: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(detalhes_compra, c) for c in compras_detalhar]
        for future in as_completed(futures):
            try:
                id_compra, itens, contratos_compra, atas_compra = future.result()
                compra_itens[id_compra] = itens
                for contrato in contratos_compra:
                    contrato["idCompra"] = contrato.get("idCompra") or id_compra
                    contrato["statusCalculado"] = status_contrato(contrato)
                    contratos.append(contrato)
                for ata in atas_compra:
                    ata["idCompra"] = ata.get("idCompra") or id_compra
                    atas.append(ata)
            except Exception as exc:
                print(f"Aviso detalhes: {exc}")

    # Contratos e atas passam a vir do próprio PNCP e conservam o número de
    # controle da contratação, evitando vínculos indiretos por UASG.
    contratos = list({(c.get("numeroControlePncpContrato") or c.get("numeroControlePNCP") or c.get("numeroContratoEmpenho"), c.get("idCompra")): c for c in contratos}.values())
    atas = list({(a.get("numeroControlePNCPAta") or a.get("numeroControlePncpAta") or a.get("numeroAtaRegistroPreco"), a.get("idCompra")): a for a in atas}.values())

    pgc_indice = {(p.get("orgao"), int(p.get("anoPcaProjetoCompra") or 0), str(p.get("codigoUasg")), int(p.get("numeroItemPncp") or 0)): p for p in pgc}
    compras_por_chave: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    compras_por_descricao: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    itens_compras_saida: list[dict[str, Any]] = []
    compras_oficiais: dict[tuple[str, str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for compra in compras:
        chave_oficial = (str(compra.get("orgaoEntidadeCnpj")), str(compra.get("unidadeOrgaoCodigoUnidade")), int(compra.get("anoCompraPncp") or 0), str(compra.get("numeroCompra") or "").lstrip("0") or "0")
        compras_oficiais[chave_oficial].append(compra)
        for item in compra_itens.get(compra["idCompra"], []):
            codigo = str(item.get("catalogoCodigoItem") or item.get("codigoItem") or "")
            registro = {"idCompra": compra["idCompra"], "cnpj": compra["orgaoEntidadeCnpj"], "codigoUnidade": str(compra["unidadeOrgaoCodigoUnidade"]), "anoCompra": compra["anoCompraPncp"], **item}
            itens_compras_saida.append(registro)
            if codigo:
                compras_por_chave[(compra["orgaoEntidadeCnpj"], str(compra["unidadeOrgaoCodigoUnidade"]), codigo)].append({"compra": compra, "item": item})
            descricao_normalizada = normalizar(item.get("descricao"))
            if descricao_normalizada:
                compras_por_descricao[(compra["orgaoEntidadeCnpj"], str(compra["unidadeOrgaoCodigoUnidade"]), descricao_normalizada)].append({"compra": compra, "item": item})

    vinculos: list[dict[str, Any]] = []
    contagem = defaultdict(int)
    for item in base["itens"]:
        chave = (item["cnpj"], int(item["anoPca"]), str(item["codigoUnidade"]), int(item["numeroItem"] or 0))
        projeto = pgc_indice.get(chave)
        codigo_futuro = str(item.get("numeroContratacaoFutura") or item.get("grupoCodigo") or "")
        match_futuro = re.fullmatch(r"(\d+)-(\d+)/(\d{4})", codigo_futuro)
        oficiais: list[dict[str, Any]] = []
        if match_futuro:
            uasg_futura, numero_futuro, ano_futuro = match_futuro.groups()
            oficiais = compras_oficiais.get((item["cnpj"], uasg_futura, int(ano_futuro), numero_futuro.lstrip("0") or "0"), [])
        candidatos = compras_por_chave.get((item["cnpj"], str(item["codigoUnidade"]), str(item.get("codigoItem") or "")), [])
        if not candidatos:
            candidatos = compras_por_descricao.get((item["cnpj"], str(item["codigoUnidade"]), normalizar(item.get("descricao"))), [])
        janela = []
        for candidato in candidatos:
            ano_publicacao = int(str(candidato["compra"].get("dataPublicacaoPncp") or "0")[:4] or 0)
            if item["anoPca"] - 1 <= ano_publicacao <= item["anoPca"]:
                janela.append(candidato)
        nivel, compra_ref, motivo, tipo_vinculo = "Não iniciada/sem vínculo", None, "Nenhuma contratação pública compatível localizada", "Não encontrado"
        if len(oficiais) == 1:
            compra_ref = oficiais[0]["idCompra"]
            nivel, tipo_vinculo = "Compra localizada (confirmada PNCP)", "Confirmado PNCP"
            motivo = "Vínculo oficial pelo identificador da futura contratação do PCA (UASG-número/ano)"
        if projeto and projeto.get("statusContratacaoExecucao") is True:
            if not compra_ref:
                nivel, tipo_vinculo = "Iniciada (confirmada)", "Confirmado"
                motivo = "Indicador de execução informado pelo PGC"
        if janela and not compra_ref:
            descricao = normalizar(item.get("descricao"))
            janela.sort(key=lambda c: len(set(descricao.split()) & set(normalizar(c["item"].get("descricao")).split())), reverse=True)
            compra_ref = janela[0]["compra"]["idCompra"]
            nivel = "Compra localizada (provável)" if nivel != "Iniciada (confirmada)" else nivel
            tipo_vinculo = "Provável" if nivel == "Compra localizada (provável)" else tipo_vinculo
            motivo = "Correspondência por CNPJ, UASG, item de catálogo/descrição e janela do PCA"
        contratos_ref = [c for c in contratos if c.get("idCompra") == compra_ref] if compra_ref else []
        if contratos_ref:
            nivel = "Contrato formalizado"
            tipo_vinculo = "Confirmado PNCP"
        atas_ref = [a for a in atas if a.get("idCompra") == compra_ref] if compra_ref else []
        contagem[nivel] += 1
        vinculos.append({
            "chaveItemPca": "|".join(map(str, chave)), "cnpj": item["cnpj"], "anoPca": item["anoPca"],
            "codigoUnidade": item["codigoUnidade"], "numeroItem": item["numeroItem"], "idCompra": compra_ref,
            "situacaoCiclo": nivel, "tipoVinculo": tipo_vinculo,
            "motivoVinculo": motivo, "numeroArtefato": projeto.get("numeroArtefato") if projeto else None,
            "statusContratacaoExecucao": projeto.get("statusContratacaoExecucao") if projeto else None,
            "numeroContratacaoFutura": codigo_futuro or None,
            "numeroControlePncpCompra": oficiais[0].get("numeroControlePNCP") if len(oficiais) == 1 else None,
            "quantidadeAtas": len(atas_ref), "quantidadeContratos": len(contratos_ref),
        })

    saida = {
        "metadata": {"extraidoEm": datetime.now().astimezone().isoformat(timespec="seconds"), "fontes": [COMPRAS_API, PNCP_API], "modalidadesConsultadas": MODALIDADES, "periodosConsultados": periodos(), "observacao": "Vínculos prováveis não equivalem a confirmação administrativa."},
        "resumo": {"projetosPgc": len(pgc), "compras": len(compras), "atas": len(atas), "contratos": len(contratos), "itensCompra": sum(map(len, compra_itens.values())), "situacoes": dict(contagem)},
        "vinculos": vinculos, "compras": compras, "itensCompras": itens_compras_saida, "atas": atas, "contratos": contratos,
    }
    (DATA / "ciclo_compras_sesap.json").write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Concluído em {time.time()-inicio_exec:.1f}s: {len(pgc)} PGC, {len(compras)} compras, {len(contratos)} contratos.")


if __name__ == "__main__":
    executar()
