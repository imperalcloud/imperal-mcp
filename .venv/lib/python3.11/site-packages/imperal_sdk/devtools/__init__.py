# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Developer/CI utility scripts for the Imperal SDK.

Moved from imperal_sdk.tools (which was removed — the dead ctx.tools IPC
surface that was never wired by the kernel).

    generate_api_surface  — emit public ctx.* surface JSON for kernel linter
    validate_identity_contract — auth-gw DB vs SDK Pydantic drift checker
"""
from imperal_sdk.devtools.generate_api_surface import generate_surface
from imperal_sdk.devtools.validate_identity_contract import (
    EXCLUDED_FROM_API,
    validate_user_against_db,
    validate_tenant_against_db,
    validate_subset_invariants,
)

__all__ = [
    "generate_surface",
    "EXCLUDED_FROM_API",
    "validate_user_against_db",
    "validate_tenant_against_db",
    "validate_subset_invariants",
]
