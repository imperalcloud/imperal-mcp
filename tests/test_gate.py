from imperal_mcp.gate import is_read_only, is_synthetic


def test_read_allowed():
    assert is_read_only("list_links", "read") is True

def test_write_and_destructive_refused():
    assert is_read_only("save_link", "write") is False
    assert is_read_only("wipe", "destructive") is False

def test_missing_action_type_fails_closed():
    assert is_read_only("mystery", None) is False
    assert is_read_only("mystery", "") is False

def test_legacy_chat_orchestrator_fails_closed():
    assert is_read_only("tool_msads_chat", "read") is False

def test_synthetic_detection():
    for n in ("__panel__home", "__widget__x", "__webhook__y", "skeleton_z", "_internal_q"):
        assert is_synthetic(n) is True
    assert is_synthetic("list_links") is False
