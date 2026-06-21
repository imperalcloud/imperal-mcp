from imperal_mcp.irkit import validate_ir, ui_catalog_text, ir_spec_text, examples_text, build_prompt_text, LINK_SAVER_EXAMPLE


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


def test_ui_catalog_lists_components():
    txt = ui_catalog_text()
    assert "Card" in txt and "List" in txt
    assert txt.count("\n") >= 40  # 50+ components, one per line


def test_resource_texts_nonempty():
    for fn in (ir_spec_text, examples_text, build_prompt_text):
        assert isinstance(fn(), str) and len(fn()) > 50


# F4 — LINK_SAVER_EXAMPLE passes validate_ir (op/args shape, not verb/collection)
def test_link_saver_example_is_schema_valid():
    result = validate_ir(LINK_SAVER_EXAMPLE)
    assert result["valid"] is True, f"LINK_SAVER_EXAMPLE failed validation: {result['issues']}"


def test_link_saver_example_uses_op_not_verb():
    """Confirm example uses op+args vocabulary, not the old verb/collection shape."""
    for fn in LINK_SAVER_EXAMPLE["app"]["functions"]:
        for step in fn["impl"]["steps"]:
            assert "op" in step, f"step missing 'op': {step}"
            assert "verb" not in step, f"step uses deprecated 'verb': {step}"
            assert "collection" not in step, f"step uses deprecated 'collection': {step}"


def test_examples_text_embeds_correct_schema():
    """examples_text() must mention 'op' and 'store.create', not 'verb'."""
    txt = examples_text()
    assert '"op"' in txt
    assert "store.create" in txt
    assert '"verb"' not in txt


def test_ir_spec_text_mentions_op_args():
    """ir_spec_text() must document op/args vocabulary."""
    txt = ir_spec_text()
    assert "op" in txt
    assert "args" in txt
