"""Inspeciona planilhas XLSX sem dependências externas."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def column_number(ref: str) -> int:
    letters = "".join(c for c in ref if c.isalpha())
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter.upper()) - 64
    return value - 1


def workbook_rows(path: Path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.findall(".//m:t", NS)) for item in root.findall("m:si", NS)]

        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("p:Relationship", REL_NS)}
        for sheet in book.findall("m:sheets/m:sheet", NS):
            name = sheet.attrib["name"]
            target = targets[sheet.attrib[f"{{{NS['r']}}}id"]]
            sheet_path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            root = ET.fromstring(archive.read(sheet_path))
            rows = []
            for row in root.findall("m:sheetData/m:row", NS):
                values = []
                for cell in row.findall("m:c", NS):
                    index = column_number(cell.attrib.get("r", "A1"))
                    while len(values) <= index:
                        values.append("")
                    kind = cell.attrib.get("t")
                    value_node = cell.find("m:v", NS)
                    if kind == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
                    elif value_node is None:
                        value = ""
                    elif kind == "s":
                        value = shared[int(value_node.text)]
                    else:
                        value = value_node.text or ""
                    values[index] = value.strip() if isinstance(value, str) else value
                if any(value != "" for value in values):
                    rows.append(values)
            yield name, rows


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        path = Path(filename)
        print(f"\n### {path.name}")
        for sheet_name, rows in workbook_rows(path):
            print(f"\n[{sheet_name}] {len(rows)} linhas")
            for row in rows[:25]:
                print(" | ".join(str(value) for value in row))
