# -*- coding: utf-8 -*-
# Copyright (c) 2026 Imperal, Inc.
# Licensed under the AGPL-3.0 License.
"""Universal ICNLI MCP Core Runtime — Python 3.6+ compatible, zero-dependency.

Designed for headless edge nodes, legacy OS environments, and cloud targets.
Supports:
- Python 3.6+ typing without PEP 585/604 syntax.
- Zero external dependencies (pure stdlib).
- Signal handling & cooperative cancellation tokens.
- Bidirectional progress and stdout/stderr chunk streaming.
- ICNLI Declarative UI components (EntityList, ConfirmationGate, StatCard).
"""
import sys
import os
import json
import time
import signal
import threading
from typing import Any, Dict, List, Optional, Union, Callable

__version__ = "2.0.0"


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()
        self._callbacks = []  # type: List[Callable[[], None]]

    def is_cancelled(self):
        # type: () -> bool
        with self._lock:
            return self._cancelled

    def cancel(self):
        # type: () -> None
        callbacks_to_fire = []
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                callbacks_to_fire = list(self._callbacks)
        for cb in callbacks_to_fire:
            try:
                cb()
            except Exception:
                pass

    def on_cancelled(self, callback):
        # type: (Callable[[], None]) -> None
        with self._lock:
            if self._cancelled:
                fire = True
            else:
                self._callbacks.append(callback)
                fire = False
        if fire:
            try:
                callback()
            except Exception:
                pass


class StreamEmitter:
    """Streams JSON-RPC / MCP events to standard output with flush."""

    def __init__(self, out_stream=None):
        self._stream = out_stream if out_stream is not None else sys.stdout
        self._lock = threading.Lock()

    def emit_event(self, event_type, payload):
        # type: (str, Dict[str, Any]) -> None
        message = {
            "type": event_type,
            "timestamp": time.time(),
            "payload": payload,
        }
        raw = json.dumps(message, ensure_ascii=False)
        with self._lock:
            self._stream.write(raw + "\n")
            self._stream.flush()

    def emit_progress(self, percent, message=""):
        # type: (float, str) -> None
        pct = max(0.0, min(100.0, float(percent)))
        self.emit_event("progress", {"percent": pct, "message": str(message)})

    def emit_chunk(self, chunk, stream_name="stdout"):
        # type: (str, str) -> None
        self.emit_event("stream_chunk", {"chunk": chunk, "stream": stream_name})


class SchemaValidator:
    """Pure stdlib JSON Schema Draft 7 validator (types, required, enum)."""

    @staticmethod
    def validate(instance, schema):
        # type: (Any, Dict[str, Any]) -> List[str]
        errors = []  # type: List[str]
        if not isinstance(schema, dict):
            return errors

        schema_type = schema.get("type")
        if schema_type:
            type_valid = True
            if schema_type == "string" and not isinstance(instance, str):
                type_valid = False
            elif schema_type == "integer" and (not isinstance(instance, int) or isinstance(instance, bool)):
                type_valid = False
            elif schema_type == "number" and (not isinstance(instance, (int, float)) or isinstance(instance, bool)):
                type_valid = False
            elif schema_type == "boolean" and not isinstance(instance, bool):
                type_valid = False
            elif schema_type == "array" and not isinstance(instance, (list, tuple)):
                type_valid = False
            elif schema_type == "object" and not isinstance(instance, dict):
                type_valid = False

            if not type_valid:
                errors.append("Expected type '{}', got '{}'".format(schema_type, type(instance).__name__))
                return errors

        if isinstance(instance, dict):
            required = schema.get("required") or []
            for req_field in required:
                if req_field not in instance:
                    errors.append("Missing required property '{}'".format(req_field))

            properties = schema.get("properties") or {}
            for prop_name, prop_schema in properties.items():
                if prop_name in instance:
                    sub_errors = SchemaValidator.validate(instance[prop_name], prop_schema)
                    for err in sub_errors:
                        errors.append("{}: {}".format(prop_name, err))

        if "enum" in schema and isinstance(schema["enum"], (list, tuple)):
            if instance not in schema["enum"]:
                errors.append("Value {!r} not in enum {!r}".format(instance, schema["enum"]))

        return errors


class ICNLIComponent:
    """Standard ICNLI Declarative Component constructors."""

    @staticmethod
    def entity_list(items, total_count=None, omitted_count=0):
        # type: (List[Dict[str, Any]], Optional[int], int) -> Dict[str, Any]
        tot = total_count if total_count is not None else len(items)
        return {
            "component": "EntityList",
            "items": items,
            "total": tot,
            "shown": len(items),
            "omitted": omitted_count,
        }

    @staticmethod
    def confirmation_gate(operation, affected_items, risk_level="high", message=""):
        # type: (str, List[Any], str, str) -> Dict[str, Any]
        return {
            "component": "ConfirmationGate",
            "operation": operation,
            "risk": risk_level,
            "affected_count": len(affected_items),
            "affected_items": affected_items,
            "message": message or "Are you sure you want to proceed with {}?".format(operation),
        }

    @staticmethod
    def stat_card(label, value, delta=None, status="normal"):
        # type: (str, Union[str, int, float], Optional[str], str) -> Dict[str, Any]
        card = {
            "component": "StatCard",
            "label": label,
            "value": value,
            "status": status,
        }
        if delta is not None:
            card["delta"] = delta
        return card
