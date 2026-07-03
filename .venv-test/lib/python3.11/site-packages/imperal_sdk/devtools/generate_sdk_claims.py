# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Emit the SDK's claims about the kernel for the contract guard.

Output: {"constants": {...}, "decorator_roles": {...}}. Read by the SDK-side
guard (tests/contract) and the kernel-CI guard (Plan 1b). Cross-checked
against kernel-contract.json by imperal_sdk.devtools.contract_checks.

Regenerated via:
    python -m imperal_sdk.devtools.generate_sdk_claims --output sdk_claims.json
"""
from __future__ import annotations

import json
from pathlib import Path

# Decorator-field roles the SDK asserts about the kernel. Cross-checked
# against kernel-contract.consumed_decorator_fields by check_decorator_roles.
_DECORATOR_ROLES = {
    "action_type": "consumed",
    "chain_callable": "consumed",
    "data_model": "consumed",
    "event": "consumed",
    "id_projection": "consumed",
    "effects": "advisory",
    "background": "advisory",
    "long_running": "advisory",
}

# HTTP payload field-sets the SDK billing client actually sends, per route.
# Cross-checked against the kernel/gateway request model by the Phase 1b
# contract guard (wire layer b). Sourced from billing/client.py::track_usage,
# which posts {"meter", "quantity"} and adds {"user_id", "tenant_id"} when a
# user is bound. The corrected field is 'quantity' (the 2026-05-30 fix); the
# stale 'amount' field must never reappear here.
_HTTP_PAYLOADS: dict[str, list[str]] = {
    "POST /v1/billing/internal/usage/track": ["meter", "quantity", "user_id", "tenant_id"],
    "POST /v1/billing/change-plan": ["plan_id", "period"],
    "POST /v1/billing/topup": ["tokens", "price_cents", "save_payment_method", "off_session"],
    "POST /v1/billing/payment-methods/setup": [],
}


def generate_claims() -> dict:
    import imperal_sdk
    from imperal_sdk.extensions.client import MAX_CALL_DEPTH
    return {
        # The SDK version these claims were generated from. The kernel-side
        # guard compares this against the installed imperal_sdk to detect a
        # deployed-vs-validated drift — so a stale artifact snapshot can never
        # read green against a different SDK than the one actually deployed.
        "_sdk_version": imperal_sdk.__version__,
        "constants": {
            # SDK call_stack INCLUDES the root (starts at len 1), so counts_root=True.
            "max_call_depth": {"value": MAX_CALL_DEPTH, "counts_root": True},
        },
        "decorator_roles": dict(_DECORATOR_ROLES),
        "http_payloads": {k: list(v) for k, v in _HTTP_PAYLOADS.items()},
    }


def main(output: Path | None = None) -> None:
    payload = json.dumps(generate_claims(), indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Emit SDK contract claims JSON.")
    p.add_argument("--output", type=Path, default=None)
    main(p.parse_args().output)
