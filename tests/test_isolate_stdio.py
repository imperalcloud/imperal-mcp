"""Field gate 2026-11-15 (Windows): every git child of the MCP server held the protocol's stdin pipe -- a checkpoint
waited 60 s, the index never finished. The server keeps the channel to itself; children get the null device."""
import os
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(os.name == "nt", reason="the POSIX run of the same rule (Windows: os-check field gate)")
def test_a_child_of_the_server_never_reads_or_writes_the_protocol():
    prog = textwrap.dedent("""
        import subprocess, sys
        from imperal_mcp.cli import isolate_stdio
        isolate_stdio()
        child = subprocess.run(["cat"], capture_output=False, timeout=10)      # inherits stdin/stdout
        subprocess.run([sys.executable, "-c", "print('child-out')"], timeout=10)
        line = sys.stdin.readline()
        sys.stdout.write("server-read:" + line)
    """)
    p = subprocess.run([sys.executable, "-c", prog], input="PROTOCOL\nmore\n", capture_output=True, text=True,
                       timeout=60, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert p.returncode == 0, p.stderr
    assert p.stdout == "server-read:PROTOCOL\n"                 # the protocol reached the server whole
    assert "child-out" in p.stderr and "child-out" not in p.stdout   # a child's print goes to the log
