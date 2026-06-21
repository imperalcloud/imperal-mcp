# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Emit the SDK reference — the single owner of API facts (signatures,
defaults, required-ness, return annotations, declared enums).

Covers the ENTIRE important public surface (scope expansion 2026-06-19,
Valentin): client methods, ui components, decorators, sdl facet roles, sdl
helper functions, and the result/def dataclasses. Each is derived from the
code's own public API so the artifact can never silently miss a symbol.

Output shape:
    {
      "sdk_version": str,
      "symbols": {
        "<qualified.name>": {
          "kind": "client_method" | "ui_component" | "decorator"
                | "sdl_role" | "sdl_func" | "dataclass",
          "params": [{"name", "annotation", "default", "required"}],
          "returns": str | None,
          "enums": {"<param>": [str, ...]}
        }
      }
    }

Annotations are the raw string form (the introspected modules use
``from __future__ import annotations``), which keeps the artifact stable and
diff-friendly. Subsumes ``api_surface.json`` (the method-name surface is a
projection of this richer reference).

Regenerated via:
    python -m imperal_sdk.devtools.generate_reference --output sdk-reference.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from imperal_sdk.devtools.reference import (
    client_methods,
    dataclasses_kind,
    decorators,
    sdl_funcs,
    sdl_roles,
    ui_components,
)

# Each collector owns one kind; merged in a fixed order, then sorted.
_COLLECTORS = (
    client_methods.collect,
    ui_components.collect,
    decorators.collect,
    sdl_roles.collect,
    sdl_funcs.collect,
    dataclasses_kind.collect,
)


def generate_reference() -> dict[str, Any]:
    import imperal_sdk

    symbols: dict[str, dict[str, Any]] = {}
    for collect in _COLLECTORS:
        symbols.update(collect())
    return {
        "sdk_version": imperal_sdk.__version__,
        "symbols": dict(sorted(symbols.items())),
    }


def main(output: Path | None = None) -> None:
    payload = json.dumps(generate_reference(), indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Emit SDK reference JSON.")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    main(args.output)
