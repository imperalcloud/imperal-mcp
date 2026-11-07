"""Ignat 06.11 §4.1/§4.5: a cut impact answer hid the other repositories' users behind the library's own tests,
halved the query echo and reported the display list's length as the total."""
from imperal_mcp import exoskeleton as ex


def test_query_echo_is_never_cut_and_total_reads_more():
    obj = {"queried_symbols": ["Section", "SectionCard"],
           "changed_together": [f"f{i}.py (0.5)" for i in range(8)] + ["+57 more"],
           "items": [{"id": f"x{i}", "title": "y" * 300} for i in range(200)]}
    out = ex.bounded(obj, limit=6000)
    assert out["queried_symbols"] == ["Section", "SectionCard"]
    assert out.get("changed_together_total", 65) == 65


def test_code_of_any_repo_comes_before_tests():
    items = [{"id": "lib/tests/t1.py", "group": "tests"}, {"id": "lib/tests/t2.py", "group": "tests"},
             {"id": "mod_a/x.py", "group": "code", "outside_folder": True}, {"id": "lib/src/s.py", "group": "code"}]
    assert [i["id"] for i in ex.code_first(items)] == ["mod_a/x.py", "lib/src/s.py", "lib/tests/t1.py",
                                                       "lib/tests/t2.py"]


def test_folder_merge_one_file_once_code_first_newest_sync():
    own = {"ok": True, "synced_at": 100.0, "data": {"items": [
        {"id": "tests/t.py", "title": "tests/t.py", "path": "tests/t.py", "group": "tests"},
        {"id": "app/x.py", "title": "app/x.py", "path": "app/x.py", "group": "code"}]}}
    other = {"ok": True, "synced_at": 300.0, "data": {"items": [
        {"id": "m.py", "title": "m.py", "path": "m.py", "group": "code"},
        {"id": "p", "title": "p", "path": "core/gw/app/x.py", "origin": "package", "repo": "folderkey",
         "repo_name": "wpanel", "group": "code"}]}}
    out = ex._merge_folder_answers([("core/gw", own), ("mods/a", other)], units_by_key={"k1": "core/gw"})
    paths = [i["path"] for i in out["data"]["items"]]
    assert sum(p.endswith("app/x.py") for p in paths) == 1
    assert paths[-1].endswith("tests/t.py")
    assert out["synced_at"] == 300.0
