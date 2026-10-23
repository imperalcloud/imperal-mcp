"""The `imperal-mcp` command on any Python from 3.7 (imperal_mcp/_launch.py).

On 3.10+ it is imperal_mcp.server.main itself; on 3.7-3.9 it runs the same release on a Python 3.12
set up once with uv. Real installs on 3.7/3.8/3.9 are checked in containers before a release;
these pin the decisions."""
import hashlib
import io
import os
import sys
import tarfile

import pytest

from imperal_mcp import _launch as L


def test_native_python_runs_the_cli_directly(monkeypatch):
    called = []
    import imperal_mcp.server
    monkeypatch.setattr(imperal_mcp.server, "main", lambda: called.append("cli"))
    monkeypatch.setattr(L, "runtime", lambda v: pytest.fail("no runtime on a native Python"))
    L.main()
    assert called == ["cli"]


def test_old_python_execs_the_runtime_with_the_same_arguments(monkeypatch):
    monkeypatch.setattr(L, "NATIVE", (99, 0))
    monkeypatch.setattr(L, "_WINDOWS", False)
    monkeypatch.setattr(L, "runtime", lambda v: "/rt/bin/imperal-mcp")
    monkeypatch.setattr(sys, "argv", ["imperal-mcp", "login"])
    seen = []
    monkeypatch.setattr(os, "execv", lambda exe, argv: seen.append((exe, argv)))
    L.main()
    assert seen == [("/rt/bin/imperal-mcp", ["/rt/bin/imperal-mcp", "login"])]


def test_a_failed_setup_says_how_to_install_and_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(L, "NATIVE", (99, 0))

    def boom(v):
        raise RuntimeError("no network")
    monkeypatch.setattr(L, "runtime", boom)
    with pytest.raises(SystemExit) as e:
        L.main()
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "no network" in err and "uv tool install imperal-mcp" in err


def test_a_ready_runtime_is_reused_without_uv(monkeypatch, tmp_path):
    monkeypatch.setenv(L.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(L, "_WINDOWS", False)
    prefix = tmp_path / ("py%s-1.2.3" % L.RUNTIME_PYTHON)
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "imperal-mcp").write_text("")
    (prefix / ".ready").write_text("")
    monkeypatch.setattr(L, "_find_uv", lambda home: pytest.fail("a ready runtime needs no uv"))
    assert L.runtime("1.2.3") == str(prefix / "bin" / "imperal-mcp")


def test_setup_installs_this_release_marks_it_ready_and_drops_older_ones(monkeypatch, tmp_path):
    monkeypatch.setenv(L.HOME_ENV, str(tmp_path))
    monkeypatch.delenv(L.SPEC_ENV, raising=False)
    monkeypatch.setattr(L, "_WINDOWS", False)
    (tmp_path / "py3.12-0.0.1").mkdir()                      # an earlier release's environment
    monkeypatch.setattr(L, "_find_uv", lambda home: "/x/uv")
    calls = []

    def fake_call(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "venv":
            os.makedirs(os.path.join(cmd[-1], "bin"))
        else:
            open(os.path.join(os.path.dirname(cmd[cmd.index("--python") + 1]), "imperal-mcp"), "w").close()
        return 0
    monkeypatch.setattr(L.subprocess, "check_call", fake_call)
    exe = L.runtime("1.2.3")
    prefix = tmp_path / "py3.12-1.2.3"
    assert exe == str(prefix / "bin" / "imperal-mcp")
    assert calls[0][:2] == ["/x/uv", "venv"] and L.RUNTIME_PYTHON in calls[0]
    assert calls[1][-1] == "imperal-mcp==1.2.3"                   # the SAME release, never "latest"
    assert (prefix / ".ready").exists()
    assert not (tmp_path / "py3.12-0.0.1").exists()


def test_a_half_made_runtime_is_set_up_again(monkeypatch, tmp_path):
    monkeypatch.setenv(L.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(L, "_WINDOWS", False)
    prefix = tmp_path / "py3.12-1.2.3"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "imperal-mcp").write_text("")                # no .ready: setup was interrupted
    monkeypatch.setattr(L, "_find_uv", lambda home: "/x/uv")
    calls = []

    def fake_call(cmd, **kw):
        calls.append(cmd[1])
        if cmd[1] == "venv":
            os.makedirs(os.path.join(cmd[-1], "bin"))
        else:
            open(os.path.join(os.path.dirname(cmd[cmd.index("--python") + 1]), "imperal-mcp"), "w").close()
        return 0
    monkeypatch.setattr(L.subprocess, "check_call", fake_call)
    L.runtime("1.2.3")
    assert calls == ["venv", "pip"]


@pytest.mark.parametrize("plat,machine,libc,want", [
    ("linux", "x86_64", "glibc", "x86_64-unknown-linux-gnu"),
    ("linux", "x86_64", "", "x86_64-unknown-linux-musl"),
    ("linux", "aarch64", "glibc", "aarch64-unknown-linux-gnu"),
    ("linux", "armv7l", "glibc", "armv7-unknown-linux-gnueabihf"),
    ("darwin", "arm64", "", "aarch64-apple-darwin"),
    ("darwin", "x86_64", "", "x86_64-apple-darwin"),
])
def test_uv_build_for_the_machine(monkeypatch, plat, machine, libc, want):
    monkeypatch.setattr(L.sys, "platform", plat)
    monkeypatch.setattr(L, "_WINDOWS", False)
    monkeypatch.setattr(L.platform, "machine", lambda: machine)
    monkeypatch.setattr(L.platform, "libc_ver", lambda: (libc, ""))
    assert L._uv_target() == want


def _uv_tarball():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        body = b"#!/bin/sh\necho uv\n"
        info = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu/uv")
        info.size = len(body)
        t.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def test_uv_download_is_checked_and_unpacked(monkeypatch, tmp_path):
    data = _uv_tarball()
    monkeypatch.setattr(L, "_WINDOWS", False)
    monkeypatch.setattr(L, "_uv_target", lambda: "x86_64-unknown-linux-gnu")
    monkeypatch.setattr(L, "_fetch", lambda url: (hashlib.sha256(data).hexdigest() + "  x").encode()
                        if url.endswith(".sha256") else data)
    uv = L._install_uv(str(tmp_path))
    assert uv == str(tmp_path / "uv" / "uv") and os.access(uv, os.X_OK)


def test_a_uv_download_that_does_not_match_its_checksum_is_refused(monkeypatch, tmp_path):
    data = _uv_tarball()
    monkeypatch.setattr(L, "_uv_target", lambda: "x86_64-unknown-linux-gnu")
    monkeypatch.setattr(L, "_fetch", lambda url: b"0" * 64 if url.endswith(".sha256") else data)
    with pytest.raises(RuntimeError, match="SHA-256"):
        L._install_uv(str(tmp_path))
    assert not (tmp_path / "uv" / "uv").exists()


def test_the_launcher_stays_python_37_syntax():
    """It is the only module an old interpreter runs: no 3.8+ syntax (walrus, positional-only
    parameters) and no annotations that need newer typing."""
    import ast
    src = open(L.__file__).read()
    tree = ast.parse(src, feature_version=(3, 7))
    assert not any(isinstance(n, ast.NamedExpr) for n in ast.walk(tree))
    for mod in ("__init__.py", "core.py"):              # what importing the launcher pulls in
        ast.parse(open(os.path.join(os.path.dirname(L.__file__), mod)).read(), feature_version=(3, 7))


def test_the_launcher_says_nothing_on_stdout(monkeypatch, tmp_path, capsys):
    """stdout is the MCP channel: setup progress and uv's own output go to stderr."""
    monkeypatch.setenv(L.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(L, "_WINDOWS", False)
    monkeypatch.setattr(L, "_find_uv", lambda home: "/x/uv")
    seen = []

    def fake_call(cmd, **kw):
        seen.append(kw.get("stdout"))
        if cmd[1] == "venv":
            os.makedirs(os.path.join(cmd[-1], "bin"))
        else:
            open(os.path.join(os.path.dirname(cmd[cmd.index("--python") + 1]), "imperal-mcp"), "w").close()
        return 0
    monkeypatch.setattr(L.subprocess, "check_call", fake_call)
    L.runtime("1.2.3")
    assert seen == [sys.stderr, sys.stderr]
    assert capsys.readouterr().out == ""


def test_the_package_imports_without_importlib_metadata(monkeypatch):
    """Python 3.7 has no importlib.metadata: importing imperal_mcp (the launcher lives in it)
    must still work there."""
    import builtins
    import importlib
    import imperal_mcp
    real = builtins.__import__

    def no_metadata(name, *a, **kw):
        if name == "importlib.metadata":
            raise ImportError(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_metadata)
    try:
        importlib.reload(imperal_mcp)
        assert imperal_mcp.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(imperal_mcp)


def test_a_repository_config_cannot_steer_the_runtime_install(monkeypatch, tmp_path):
    """Started inside someone's repository: its uv.toml / pyproject.toml / .python-version must not
    choose the index or the interpreter -- uv runs with --no-config from the launcher's own folder."""
    monkeypatch.setenv(L.HOME_ENV, str(tmp_path))
    monkeypatch.setattr(L, "_WINDOWS", False)
    monkeypatch.setattr(L, "_find_uv", lambda home: "/x/uv")
    seen = []

    def fake_call(cmd, **kw):
        seen.append((cmd, kw.get("cwd")))
        if cmd[1] == "venv":
            os.makedirs(os.path.join(cmd[-1], "bin"))
        else:
            open(os.path.join(os.path.dirname(cmd[cmd.index("--python") + 1]), "imperal-mcp"), "w").close()
        return 0
    monkeypatch.setattr(L.subprocess, "check_call", fake_call)
    L.runtime("1.2.3")
    assert len(seen) == 2
    assert all("--no-config" in cmd and cwd == str(tmp_path) for cmd, cwd in seen)
