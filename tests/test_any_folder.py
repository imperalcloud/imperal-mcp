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
    # partial, and said so: "partial" names the units still indexing (2026-11-06: never an empty "ok")
    assert out["status"] in ("ok", "partial") and (out["status"] == "partial") == bool(out.get("not_ready"))
    assert not all(u["done"] for u in out["units"])


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


def test_an_icloud_path_through_a_link_is_never_a_unit(tmp_path: Path):
    outside = tmp_path / "outside"
    (outside / "com~apple~CloudDocs").mkdir(parents=True)
    (outside / "com~apple~CloudDocs" / "x.md").write_text("# x\n")
    h = tmp_path / "home"
    (h / "Library").mkdir(parents=True)
    import os
    os.symlink(outside, h / "Library" / "Mobile Documents")
    (h / "Documents").mkdir()
    exo = ExoskeletonRuntime(workspace=str(h))
    roots = [u["root"] for u in exo.search_code("x")["units"]]
    assert roots == ["Documents"]


def test_graph_slice_and_contract_slice_answer_at_a_folder_of_repositories(tmp_path: Path):
    """Field report 06.11 #3: at a folder root graph_slice and contract_slice raised "is not a repository ... pass
    root=" while impact and search answered; contract_slice now reaches an endpoint through its handler's calls."""
    gw = tmp_path / "ws" / "gateway"
    (gw / ".git").mkdir(parents=True)
    (gw / "app").mkdir()
    (gw / "app" / "__init__.py").write_text("")
    (gw / "app" / "session.py").write_text("def session_for_sid(sid):\n    return sid\n")
    (gw / "app" / "terminal.py").write_text(
        "from fastapi import APIRouter\nfrom app.session import session_for_sid\n\nrouter = APIRouter()\n\n\n"
        "@router.post(\"/terminal/tickets\")\nasync def mint_terminal_ticket(sid: str):\n    return session_for_sid(sid)\n")
    ui = tmp_path / "ws" / "ui"
    (ui / ".git").mkdir(parents=True)
    (ui / "x.py").write_text("def other():\n    return 1\n")
    exo = ExoskeletonRuntime(workspace=str(tmp_path / "ws"))
    exo.search_code("session")                       # the first question starts the units' indexing
    _wait(exo, tmp_path / "ws")
    sl = exo.graph_slice(["session_for_sid"])
    assert [s["title"] for s in sl["symbols"]] == ["session_for_sid"]
    assert any(c.get("user") == "mint_terminal_ticket" for c in sl["symbols"][0]["callers"])
    out = exo.contract_slice(["session_for_sid"])
    got = [(c.get("route"), c.get("via"), c.get("chain")) for c in out["contracts"]]
    assert ("/terminal/tickets", "caller", "mint_terminal_ticket -> session_for_sid") in got
