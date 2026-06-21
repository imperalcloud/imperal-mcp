# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Curated, non-introspectable catalog flags (policy, not signatures).

These flags cannot be derived from introspection alone — they express
architectural intent about which symbols belong to the declarative action
vocabulary. Kept as a static curated set (like ``ui_components.enum_overrides``)
so the IR interpreter can reason about them without touching live code.
"""
from __future__ import annotations

# Symbols usable as declarative steps (the non-Turing action vocabulary).
# These are the step verbs the IR interpreter will accept in ``impl=declarative``
# functions.  Everything else is ``False``.
ACTION_VOCAB_SAFE: frozenset[str] = frozenset({
    # UI action factories
    "ui.Call",
    "ui.Navigate",
    "ui.Send",
    "ui.Open",
    # ctx.store CRUD
    "ctx.store.get",
    "ctx.store.list",
    "ctx.store.create",
    "ctx.store.update",
    "ctx.store.delete",
    # AI completion
    "ctx.ai.complete",
})


def flags_for(symbol_name: str) -> dict[str, bool]:
    """Return the policy flags for *symbol_name*.

    ``action_vocab_safe``: the symbol is an approved declarative step verb.
    ``declarative_capable``: the symbol's body could be expressed in the
    declarative action vocab.  At catalog level we mark only the vocab members
    themselves; per-app functions declare their own ``impl`` in the IR envelope.
    """
    in_vocab = symbol_name in ACTION_VOCAB_SAFE
    return {
        "action_vocab_safe": in_vocab,
        "declarative_capable": in_vocab,
    }
