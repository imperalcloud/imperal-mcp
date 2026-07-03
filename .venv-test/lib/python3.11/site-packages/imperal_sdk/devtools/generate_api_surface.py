# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Extract SDK public API surface for the docs-vs-api linter.

Output: ``{namespace: [sorted public method names]}`` JSON mapping.
Consumed by kernel-side ``docs_vs_api_linter`` (see spec §4.1) to detect
comments/docstrings referencing non-existent ``ctx.<ns>.<method>()`` calls.

Regenerated via:
    python -m imperal_sdk.devtools.generate_api_surface --output api_surface.json

Run by SDK pre-commit hook + at every release (Task 10b).
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path


def _load_namespaces() -> dict:
    """Import SDK client classes. Optional ones wrapped in try/except."""
    from imperal_sdk.store.client import StoreClient
    from imperal_sdk.config.client import ConfigClient
    from imperal_sdk.http.client import HTTPClient
    from imperal_sdk.ai.client import AIClient
    from imperal_sdk.skeleton.client import SkeletonClient
    from imperal_sdk.notify.client import NotifyClient

    nss = {
        "store": StoreClient,
        "config": ConfigClient,
        "http": HTTPClient,
        "ai": AIClient,
        "skeleton": SkeletonClient,
        "notify": NotifyClient,
    }
    try:
        from imperal_sdk.billing.client import BillingClient
        nss["billing"] = BillingClient
    except ImportError:
        pass
    try:
        from imperal_sdk.storage.client import StorageClient
        nss["storage"] = StorageClient
    except ImportError:
        pass
    return nss


def generate_surface() -> dict[str, list[str]]:
    """Return {namespace: sorted list of public callable names}.

    Public = not starting with ``_``. Callable determined via inspect.
    Deterministic and sorted for diff-friendliness.
    """
    return {
        ns: sorted(
            name for name, _ in inspect.getmembers(cls, predicate=callable)
            if not name.startswith("_")
        )
        for ns, cls in _load_namespaces().items()
    }


def main(output: Path | None = None) -> None:
    payload = json.dumps(generate_surface(), indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Emit SDK API surface JSON.")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    main(args.output)
