# -*- coding: utf-8 -*-
import io
import json
import pytest
from imperal_mcp.core import (
    CancellationToken,
    StreamEmitter,
    SchemaValidator,
    ICNLIComponent,
)


def test_cancellation_token():
    token = CancellationToken()
    assert token.is_cancelled() is False

    called = []
    token.on_cancelled(lambda: called.append(True))
    assert len(called) == 0

    token.cancel()
    assert token.is_cancelled() is True
    assert len(called) == 1

    # Adding callback after already cancelled fires immediately
    late_called = []
    token.on_cancelled(lambda: late_called.append(True))
    assert len(late_called) == 1


def test_stream_emitter():
    buf = io.StringIO()
    emitter = StreamEmitter(buf)

    emitter.emit_progress(45.5, "Processing items")
    emitter.emit_chunk("compiling binary...", stream_name="stdout")

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2

    evt1 = json.loads(lines[0])
    assert evt1["type"] == "progress"
    assert evt1["payload"]["percent"] == 45.5
    assert evt1["payload"]["message"] == "Processing items"

    evt2 = json.loads(lines[1])
    assert evt2["type"] == "stream_chunk"
    assert evt2["payload"]["chunk"] == "compiling binary..."
    assert evt2["payload"]["stream"] == "stdout"


def test_schema_validator():
    schema = {
        "type": "object",
        "required": ["name", "count"],
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "role": {"type": "string", "enum": ["admin", "user"]},
        },
    }

    # Valid instance
    valid_inst = {"name": "alice", "count": 10, "role": "admin"}
    assert SchemaValidator.validate(valid_inst, schema) == []

    # Missing required
    errs_missing = SchemaValidator.validate({"name": "alice"}, schema)
    assert any("Missing required property 'count'" in e for e in errs_missing)

    # Wrong type (boolean where integer expected)
    errs_type = SchemaValidator.validate({"name": "alice", "count": True}, schema)
    assert any("Expected type 'integer'" in e for e in errs_type)

    # Enum mismatch
    errs_enum = SchemaValidator.validate({"name": "alice", "count": 5, "role": "superadmin"}, schema)
    assert any("not in enum" in e for e in errs_enum)


def test_icnli_components():
    el = ICNLIComponent.entity_list([{"id": "u1", "name": "val"}], total_count=10, omitted_count=9)
    assert el["component"] == "EntityList"
    assert el["shown"] == 1
    assert el["total"] == 10
    assert el["omitted"] == 9

    cg = ICNLIComponent.confirmation_gate("delete_repo", ["repo1", "repo2"], risk_level="destructive")
    assert cg["component"] == "ConfirmationGate"
    assert cg["operation"] == "delete_repo"
    assert cg["risk"] == "destructive"
    assert cg["affected_count"] == 2

    sc = ICNLIComponent.stat_card("Active Users", 1250, delta="+5%", status="good")
    assert sc["component"] == "StatCard"
    assert sc["label"] == "Active Users"
    assert sc["value"] == 1250
    assert sc["delta"] == "+5%"
