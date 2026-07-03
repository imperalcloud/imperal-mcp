# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Pure SDK<->kernel contract cross-checks (Phase 1, SDK side).

Each function compares an SDK-side claim against the kernel-contract truth
and returns a list of ContractFinding (empty == they agree). No I/O.

The guiding principle (learned from the 2026-05-30 MAX_DEPTH off-by-one):
constants are compared by EFFECTIVE BEHAVIOR with an explicit model of the
counting base — never by raw value equality. Equal numbers can be wrong;
different numbers can be right.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractFinding:
    layer: str       # "wire" | "semantic" | "decorator"
    detail: str
    expected: str    # kernel truth
    actual: str      # SDK claim


def _effective_nested_calls(value: int, counts_root: bool) -> int:
    """Nested inter-extension calls a depth cap actually permits.

    A counter that EXCLUDES the root rejects at ``depth >= value`` and so
    permits ``value`` nested calls. A stack that INCLUDES the root reaches
    ``value`` at the value-th frame, permitting ``value - 1`` nested calls.
    """
    return value - 1 if counts_root else value


def check_constant_depth(sdk_claim: dict, contract: dict) -> list[ContractFinding]:
    """(c) semantic: compare EFFECTIVE allowance, never the raw value."""
    k = contract["constants"]["hub_dispatch"]["max_depth"]
    s = sdk_claim["constants"]["max_call_depth"]
    k_eff = _effective_nested_calls(k["value"], k["counts_root"])
    s_eff = _effective_nested_calls(s["value"], s["counts_root"])
    if k_eff != s_eff:
        return [ContractFinding(
            layer="semantic",
            detail=(f"inter-extension nested-call allowance differs "
                    f"(kernel value={k['value']} counts_root={k['counts_root']} -> {k_eff}; "
                    f"sdk value={s['value']} counts_root={s['counts_root']} -> {s_eff})"),
            expected=f"effective_nested_calls={k_eff}",
            actual=f"effective_nested_calls={s_eff}",
        )]
    return []


def check_wire_payload(route: str, payload_fields: set, contract: dict) -> list[ContractFinding]:
    """(b) wire: outgoing payload field names must match the server request model.

    Flags (1) fields the server does not declare (silently dropped) and
    (2) required server fields the payload never sends.
    """
    model = contract["request_models"].get(route)
    if model is None:
        return [ContractFinding("wire", f"no request model in contract for route {route!r}",
                                expected="a known route", actual=route)]
    fields = model["fields"]
    allowed = set(fields)
    required = {f for f, m in fields.items() if m.get("required")}
    sent = set(payload_fields)
    findings: list[ContractFinding] = []
    unknown = sent - allowed
    if unknown:
        findings.append(ContractFinding(
            "wire", f"payload sends field(s) the server ignores (silently dropped): {sorted(unknown)}",
            expected=f"fields subset of {sorted(allowed)}", actual=f"{sorted(sent)}"))
    missing_required = required - sent
    if missing_required:
        findings.append(ContractFinding(
            "wire", f"payload omits required server field(s): {sorted(missing_required)}",
            expected=f"includes {sorted(required)}", actual=f"{sorted(sent)}"))
    return findings


def check_decorator_roles(sdk_roles: dict, contract: dict) -> list[ContractFinding]:
    """(c): a field the SDK calls 'consumed' must be in the kernel's consumed
    list; a field marked 'advisory' must NOT be."""
    consumed = set(contract["consumed_decorator_fields"])
    findings: list[ContractFinding] = []
    for field, role in sdk_roles.items():
        if role == "consumed" and field not in consumed:
            findings.append(ContractFinding(
                "decorator", f"SDK marks {field!r} consumed but the kernel does not read it",
                expected=f"{field} in consumed_decorator_fields", actual="advisory in kernel"))
        elif role == "advisory" and field in consumed:
            findings.append(ContractFinding(
                "decorator", f"SDK marks {field!r} advisory but the kernel DOES read it",
                expected=f"{field} not in consumed_decorator_fields", actual="consumed in kernel"))
    return findings
