"""Memory plan Task 7: one protocol text tells every shell what imperal-mcp is and why it comes first."""
import asyncio


def _tool_names():
    from imperal_mcp.server import build_server
    srv = build_server(None)
    return {t.name for t in asyncio.run(srv.list_tools())}, srv


def test_the_protocol_names_every_tool_it_ships():
    from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS
    names, _srv = _tool_names()
    missing = sorted(n for n in names if f"`{n}" not in EXOSKELETON_INSTRUCTIONS)
    assert not missing, missing


def test_the_server_speaks_the_protocol():
    from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS
    _names, srv = _tool_names()
    assert srv.instructions == EXOSKELETON_INSTRUCTIONS


def test_the_protocol_is_for_any_shell_and_puts_the_frame_first():
    from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS as P
    assert "Claude Code" not in P and "any shell" in P
    assert P.index("`frame`") < P.index("`orient") and "blocked_on" in P and "first" in P.lower()
