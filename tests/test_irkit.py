from imperal_mcp.irkit import validate_ir


def test_validate_rejects_garbage():
    out = validate_ir({"not": "an ir envelope"})
    assert out["valid"] is False
    assert any(i["level"] == "ERROR" for i in out["issues"])


def test_validate_accepts_minimal_valid_envelope():
    # A structurally-valid IR envelope with no declarative steps.
    # IRApp requires `title` (no default in schema.py) — include it.
    ir = {
        "ir_version": "1",
        "app": {"id": "demo", "version": "1.0.0", "title": "Demo", "functions": []},
    }
    out = validate_ir(ir)
    assert "valid" in out and "issues" in out
    # No ERROR-level issues for a structurally valid envelope.
    assert out["valid"] == (not any(i["level"] == "ERROR" for i in out["issues"]))
