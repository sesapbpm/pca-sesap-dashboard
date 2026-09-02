"""Integra os calendários internos de 2026/2027 com PCA e execução do PNCP."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from inspecionar_xlsx import workbook_rows

ROOT = Path(__file__).resolve().parents[1]
MONTHS = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
STOP = {"A", "AS", "O", "OS", "DE", "DA", "DAS", "DO", "DOS", "E", "EM", "PARA", "COM", "POR", "UM", "UMA", "AQUISICAO", "CONTRATACAO", "SERVICO", "SERVICOS"}


def clean(value) -> str:
    return str(value or "").strip()


def norm(value) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def tokens(value) -> set[str]:
    return {word for word in norm(value).split() if len(word) > 2 and word not in STOP}


def category(value) -> str:
    value = norm(value)
    if value == "BENS" or "MATERIAL" in value:
        return "Material"
    if "TIC" in value:
        return "Soluções de TIC"
    return "Serviço" if "SERV" in value else clean(value) or "Não informada"


def month_date(value, fallback_year: int) -> str | None:
    text = norm(value)
    month = next((number for key, number in MONTHS.items() if key in text), None)
    match = re.search(r"\b(20\d{2}|2\d{2})\b", text)
    if not month:
        return None
    year = int(match.group()) if match else fallback_year
    if year < 1000:  # corrige digitação como MAIO/227
        year += 1800
    return f"{year:04d}-{month:02d}-01"


def similarity(left, right) -> float:
    a, b = tokens(left), tokens(right)
    jaccard = len(a & b) / len(a | b) if a and b else 0
    sequence = SequenceMatcher(None, norm(left), norm(right)).ratio()
    containment = len(a & b) / min(len(a), len(b)) if a and b else 0
    return max(jaccard, sequence * 0.75, containment * 0.9)


def load_calendar_rows():
    source_path = ROOT / "data/calendario_fontes.json"
    if not (ROOT / "CALENDÁRIO PCA 2027- .xlsx").exists() or not (ROOT / "MONITORAMENTO PCA 2026.xlsx").exists():
        return json.loads(source_path.read_text(encoding="utf-8"))["contratacoes"]
    rows = []
    file_2027 = ROOT / "CALENDÁRIO PCA 2027- .xlsx"
    for _, sheet_rows in workbook_rows(file_2027):
        for row in sheet_rows[1:]:
            if len(row) < 3 or not clean(row[2]):
                continue
            rows.append({"ano": 2027, "contratacaoPca": clean(row[0]), "categoriaOriginal": clean(row[1]), "categoria": category(row[1]), "objeto": clean(row[2]), "areaTecnica": clean(row[3]) if len(row) > 3 else "", "abertura": month_date(row[4] if len(row) > 4 else "", 2026), "conclusao": month_date(row[5] if len(row) > 5 else "", 2027)})
        break

    file_2026 = ROOT / "MONITORAMENTO PCA 2026.xlsx"
    for sheet_name, sheet_rows in workbook_rows(file_2026):
        if norm(sheet_name) != "GERAL":
            continue
        for row in sheet_rows[2:]:
            if len(row) < 2 or not clean(row[1]) or norm(row[0]) == "CATEGORIA":
                continue
            rows.append({"ano": 2026, "contratacaoPca": "", "categoriaOriginal": clean(row[0]), "categoria": category(row[0]), "objeto": clean(row[1]), "areaTecnica": clean(row[2]) if len(row) > 2 else "", "abertura": month_date(row[3] if len(row) > 3 else "", 2026), "conclusao": None})
        break
    source_path.write_text(json.dumps({"contratacoes": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def main():
    pca = json.loads((ROOT / "data/pca_sesap.json").read_text(encoding="utf-8"))
    cycle = json.loads((ROOT / "data/ciclo_compras_sesap.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for item in pca["itens"]:
        if item.get("grupoCodigo"):
            groups[item["grupoCodigo"]].append(item)
    candidates = {year: [] for year in (2026, 2027)}
    for code, items in groups.items():
        year = items[0].get("anoPca")
        if year in candidates and code.startswith("925550-"):
            candidates[year].append((code, items))

    links = {link["chaveItemPca"]: link for link in cycle.get("vinculos", [])}
    purchases = {str(row.get("idCompra")): row for row in cycle.get("compras", [])}
    contracts_by_purchase = defaultdict(list)
    for contract in cycle.get("contratos", []):
        contracts_by_purchase[str(contract.get("idCompra"))].append(contract)

    output = []
    for index, row in enumerate(load_calendar_rows(), 1):
        match_code, match_items, score, match_type = None, [], 0.0, "não localizado"
        if row["ano"] == 2027 and row["contratacaoPca"] in groups:
            match_code, match_items, score, match_type = row["contratacaoPca"], groups[row["contratacaoPca"]], 1.0, "exato por identificador"
        else:
            ranked = []
            for code, items in candidates[row["ano"]]:
                group_name = items[0].get("grupoNome") or ""
                score_value = similarity(row["objeto"], group_name)
                if category(items[0].get("categoria")) == row["categoria"]:
                    score_value = min(1, score_value + 0.06)
                ranked.append((score_value, code, items))
            if ranked:
                score, match_code, match_items = max(ranked, key=lambda value: value[0])
                if score >= 0.42:
                    match_type = "provável por objeto"
                else:
                    match_code, match_items, match_type = None, [], "não localizado"

        item_keys = {f"{item['cnpj']}|{item['anoPca']}|{item['codigoUnidade']}|{item['numeroItem']}" for item in match_items}
        matched_links = [links[key] for key in item_keys if key in links and links[key].get("idCompra")]
        purchase_ids = sorted({str(link["idCompra"]) for link in matched_links})
        matched_purchases = [purchases[pid] for pid in purchase_ids if pid in purchases]
        execution_match = "oficial pelo item do PCA" if matched_purchases else "não localizada"
        execution_score = 1.0 if matched_purchases else 0.0
        if not matched_purchases:
            ranked_purchases = []
            object_tokens = tokens(row["objeto"])
            for purchase in cycle.get("compras", []):
                if str(purchase.get("orgaoEntidadeCnpj")) != "08241754000145" or int(purchase.get("anoCompraPncp") or 0) not in (row["ano"] - 1, row["ano"]):
                    continue
                purchase_tokens = tokens(purchase.get("objetoCompra"))
                if len(object_tokens & purchase_tokens) < 2:
                    continue
                ranked_purchases.append((similarity(row["objeto"], purchase.get("objetoCompra")), purchase))
            if ranked_purchases:
                execution_score, probable_purchase = max(ranked_purchases, key=lambda value: value[0])
                if execution_score >= 0.62:
                    matched_purchases = [probable_purchase]
                    purchase_ids = [str(probable_purchase.get("idCompra"))]
                    execution_match = "provável por objeto"
        has_contract = any(contracts_by_purchase[pid] for pid in purchase_ids)
        status = "Concluído" if has_contract else "Iniciado" if purchase_ids else "Atrasado" if row["abertura"] and row["abertura"] < date.today().isoformat() else "No prazo"
        desired_dates = sorted(item.get("dataDesejada", "")[:10] for item in match_items if item.get("dataDesejada"))
        if not row["conclusao"] and desired_dates:
            row["conclusao"] = desired_dates[-1]
        output.append({**row, "id": f"CAL-{row['ano']}-{index:03d}", "grupoPca": match_code, "matchTipo": match_type, "matchScore": round(score, 3), "quantidadeItensPca": len(match_items), "valorPlanejado": round(sum(float(item.get("valorTotal") or 0) for item in match_items), 2), "status": status, "comprasRelacionadas": len(matched_purchases), "idsCompras": purchase_ids, "execucaoMatchTipo": execution_match, "execucaoMatchScore": round(execution_score, 3), "valorEstimadoCompras": round(sum(float(item.get("valorTotalEstimado") or 0) for item in matched_purchases), 2), "valorHomologado": round(sum(float(item.get("valorTotalHomologado") or 0) for item in matched_purchases), 2)})

    result = {"metadata": {"geradoEm": datetime.now().astimezone().isoformat(timespec="seconds"), "registros": len(output), "fonte2026": "MONITORAMENTO PCA 2026.xlsx", "fonte2027": "CALENDÁRIO PCA 2027- .xlsx"}, "contratacoes": output}
    target = ROOT / "data/calendario_pca.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    exact = sum(row["matchTipo"].startswith("exato") for row in output)
    probable = sum(row["matchTipo"].startswith("provável") for row in output)
    print(f"{len(output)} registros: {exact} exatos, {probable} prováveis, {len(output)-exact-probable} sem vínculo")


if __name__ == "__main__":
    main()
