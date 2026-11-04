"""Universal index phase 2, Task 9: outline, read_symbol and search work on documents, sheets and any language."""
import io
import subprocess
import zipfile
from pathlib import Path

import pytest

from imperal_mcp.exoskeleton import ExoskeletonRuntime


def _docx() -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    p = lambda t, s=None: (f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr>' if s else "<w:p>") + f"<w:r><w:t>{t}</w:t></w:r></w:p>"  # noqa: E731
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{p('Agreement', 'Heading1')}{p('Both agree.')}"
                                        f"{p('3.2 Payment terms', 'Heading2')}{p('Payment within 30 days.')}"
                                        "</w:body></w:document>")
    return buf.getvalue()


def _xlsx() -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns}><sheets><sheet name="Ledger" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Total</t></is></c>'
                   '<c r="B1"><v>1200</v></c></row></sheetData></worksheet>')
    return buf.getvalue()


@pytest.fixture
def ws_mixed(tmp_path: Path) -> Path:
    ws = tmp_path / "work"
    (ws / "Contracts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    (ws / "Contracts" / "NDA.docx").write_bytes(_docx())
    (ws / "ledger.xlsx").write_bytes(_xlsx())
    (ws / "app.kt").write_text("class Wallet {\n  fun pay(x: Int) = x\n}\n")
    (ws / "terms.py").write_text("def payment_terms():\n    return 30\n")
    return ws


def test_outline_and_read_a_section_of_a_docx(ws_mixed):
    exo = ExoskeletonRuntime(workspace=str(ws_mixed))
    ol = exo.outline("Contracts/NDA.docx")
    assert [s["name"] for s in ol["symbols"]][:2] == ["Agreement", "3.2 Payment terms"]
    rs = exo.read_symbol("Contracts/NDA.docx", "3.2 Payment terms")
    assert rs["status"] == "ok" and "within 30 days" in rs["rendered"]
    assert exo.read_symbol("Contracts/NDA.docx", "3.2 payment TERMS")["status"] == "ok"       # case-insensitive
    assert exo.read_symbol("ledger.xlsx", "Sheet: Ledger")["status"] == "ok"
    assert "Total | 1200" in exo.read_symbol("ledger.xlsx", "L1-2")["rendered"]


def test_outline_of_code_in_any_language(ws_mixed):
    names = [s["name"] for s in ExoskeletonRuntime(workspace=str(ws_mixed)).outline("app.kt")["symbols"]]
    assert {"Wallet", "pay"} <= set(names)


def test_search_by_file_kind(ws_mixed):
    out = ExoskeletonRuntime(workspace=str(ws_mixed)).search_code("payment terms", kind="document")
    assert out["matches"] and all(m["path"].endswith((".docx", ".pdf", ".md")) for m in out["matches"])


def test_a_tsconfig_with_comments_keeps_its_plain_outline(ws_mixed):
    (ws_mixed / "tsconfig.json").write_text('{\n  // paths\n  "compilerOptions": {"paths": {"@/*": ["./src/*"]}}\n}\n')
    assert ExoskeletonRuntime(workspace=str(ws_mixed)).outline("tsconfig.json")["status"] == "ok"
