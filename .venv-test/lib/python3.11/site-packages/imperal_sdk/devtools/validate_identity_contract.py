"""Identity contract drift validator (W1 — CI gate + sweeper backend).

Compares auth-gw SQLAlchemy User/Tenant DB columns against the
canonical Pydantic models in `imperal_sdk.types.identity`.

Exit codes:
    0 — no drift
    1 — drift detected (details on stderr)
    2 — script error (file not found, parse error)

Usage:
    python -m imperal_sdk.devtools.validate_identity_contract \\
        --authgw-path=/opt/imperal-auth-gateway/releases/initial/app
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from imperal_sdk.types.identity import User, UserContext, Tenant, TenantContext


EXCLUDED_FROM_API: dict[str, set[str]] = {
    "User": {"id", "password_hash"},
    "Tenant": {"db_config"},
}


def _extract_mapped_columns(source: str, class_name: str) -> set[str]:
    """Parse SQLAlchemy class via AST, return Mapped[...] column field names."""
    tree = ast.parse(source)
    columns: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    annotation = item.annotation
                    if isinstance(annotation, ast.Subscript):
                        if isinstance(annotation.value, ast.Name) and annotation.value.id == "Mapped":
                            columns.add(item.target.id)
    return columns


def _validate_against_db(
    model_cls: type, db_columns: set[str], excluded: set[str]
) -> list[str]:
    sdk_fields = set(model_cls.model_fields.keys())
    expected = db_columns - excluded
    extra_in_db = expected - sdk_fields
    extra_in_sdk = sdk_fields - expected
    errors: list[str] = []
    if extra_in_db:
        errors.append(
            f"{model_cls.__name__}: DB has columns not in SDK: {sorted(extra_in_db)} "
            f"(if intentionally excluded, add to EXCLUDED_FROM_API allowlist)"
        )
    if extra_in_sdk:
        errors.append(
            f"{model_cls.__name__}: SDK has fields not in DB: {sorted(extra_in_sdk)} "
            f"(SDK contract is ahead — add DB column or remove SDK field)"
        )
    return errors


def validate_user_against_db(user_py_path: str) -> list[str]:
    source = Path(user_py_path).read_text()
    db_columns = _extract_mapped_columns(source, "User")
    if not db_columns:
        return [f"Could not parse User SQLAlchemy class from {user_py_path}"]
    return _validate_against_db(User, db_columns, EXCLUDED_FROM_API["User"])


def validate_tenant_against_db(tenant_py_path: str) -> list[str]:
    source = Path(tenant_py_path).read_text()
    db_columns = _extract_mapped_columns(source, "Tenant")
    if not db_columns:
        return [f"Could not parse Tenant SQLAlchemy class from {tenant_py_path}"]
    return _validate_against_db(Tenant, db_columns, EXCLUDED_FROM_API["Tenant"])


def validate_subset_invariants() -> list[str]:
    errors: list[str] = []
    for lean, full in [(UserContext, User), (TenantContext, Tenant)]:
        missing = set(lean.model_fields.keys()) - set(full.model_fields.keys())
        if missing:
            errors.append(
                f"{lean.__name__} has fields not in {full.__name__}: {sorted(missing)}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Identity contract drift validator")
    parser.add_argument(
        "--authgw-path",
        required=True,
        help="Path to auth-gw app/ directory containing models/",
    )
    args = parser.parse_args()

    authgw = Path(args.authgw_path)
    user_py = authgw / "models" / "user.py"
    tenant_py = authgw / "models" / "tenant.py"

    if not user_py.exists() or not tenant_py.exists():
        print(
            f"ERROR: missing models at {user_py} or {tenant_py}",
            file=sys.stderr,
        )
        return 2

    all_errors = (
        validate_subset_invariants()
        + validate_user_against_db(str(user_py))
        + validate_tenant_against_db(str(tenant_py))
    )

    if all_errors:
        print("Identity contract drift detected:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Identity contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
