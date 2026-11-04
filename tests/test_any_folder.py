"""Universal index phase 2, Task 8: any folder is a workspace -- its repositories and collections are units,
indexed in the background, answered while indexing (and saying how far each unit is)."""
import io
import time
import zipfile
from pathlib import Path

import pytest

from imperal_mcp.exoskeleton import ExoskeletonRuntime


def _docx() -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    p = lambda t, s=None: (f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr>' if s else "<w:p>") + f"<w:r><w:t>{t}</w:t></w:r></w:p>"  # noqa: E731
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{p('Agreement', 'Heading1')}"
                                        f"{p('3.2 Payment terms', 'Heading2')}{p('Payment within 30 days.')}"
                                        "</w:body></w:document>")
    return buf.getvalue()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / "Projects" / "app" / ".git").mkdir(parents=True)
    (h / "Projects" / "app" / "billing.py").write_text("def settle_invoice(x):\n    return x\n")
    (h / "Documents").mkdir()
    (h / "Documents" / "NDA.docx").write_bytes(_docx())
    (h / "Desktop").mkdir()
    (h / "Desktop" / "plan.md").write_text("# Plan\\nship it\n")
    (h / "Library" / "Caches").mkdir(parents=True)
    (h / "Library" / "Caches" / "junk.pdf").write_bytes(b"%PDF-1.4")
    (h / "notes.txt").write_text("call the bank\n")
    return h


def _wait(exo, ws, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        units = exo.units_progress(str(ws))
        if units and all(u["done"] for u in units):
            return units
        time.sleep(0.05)
    raise AssertionError("units never finished")


def test_a_home_folder_is_units_and_answers_before_it_is_complete(home, monkeypatch):
    from webbee.intel import service
    real = service.IntelService._build_files
    monkeypatch.setattr(service, "BUILD_BATCH", 1)
    monkeypatch.setattr(service.IntelService, "_build_files",
                        lambda self, rels: (time.sleep(0.2), real(self, rels))[1])
    exo = ExoskeletonRuntime(workspace=str(home))
    out = exo.search_code("payment terms")
    roots = {u["root"]: u["kind"] for u in out["units"]}
    assert roots == {"Projects/app": "repo", "Projects": "collection", "Documents": "collection",
                     "Desktop": "collection", ".": "collection"}     # Projects: its loose files, not the repo in it
    assert out["status"] == "ok" and not all(u["done"] for u in out["units"])   # partial, and said so


def test_when_built_every_unit_answers_with_its_own_paths(home):
    exo = ExoskeletonRuntime(workspace=str(home))
    exo.search_code("warm up")
    _wait(exo, home)
    found = exo.search_code("settle_invoice")
    assert any(m["path"] == "Projects/app/billing.py" for m in found["matches"])
    docs = exo.search_code("Payment terms")
    assert any(m["path"] == "Documents/NDA.docx" for m in docs["matches"])
    prof = exo.repo_profile()
    assert prof["status"] == "ok" and {u["root"] for u in prof["units"]} >= {"Projects/app", "Documents"}
