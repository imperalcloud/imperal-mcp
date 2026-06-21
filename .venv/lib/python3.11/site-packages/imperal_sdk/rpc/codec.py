"""W2 codec — pure encode/decode functions for the RPC envelope.

Spec: superpowers/specs/2026-04-27-w2-pydantic-rpc-design.md §5.1.

Design rules (do not relax without spec amendment):
- Codec is pure: no env reads, no metric writes, no logging, no I/O.
- ``decode_*`` returns ``DecodeResult(request, reply, legacy_envelope)``.
  Callers MUST inspect ``legacy_envelope`` and increment a counter on True
  (see consumer files for the wired metric).
- ``strict_version`` is a per-call kwarg. Callers thread the runtime env-var
  ``IMPERAL_RPC_STRICT_VERSION`` into it; codec stays decoupled from env.
- ``encode_*`` always emits ``v: 1`` because the model defaults to it; no
  branching needed.
"""
from __future__ import annotations

import time
from typing import Any, NamedTuple

from pydantic import ValidationError

from imperal_sdk.rpc.contract import (
    ENVELOPE_VERSION,
    RpcStatus,
    RpcError,
    RpcErrorCategory,
    RpcRequest,
    RpcReply,
)


class DecodeResult(NamedTuple):
    """Return value from ``decode_request`` / ``decode_reply``.

    Exactly one of ``request`` / ``reply`` is populated; the other is None.
    ``legacy_envelope`` is True iff the input dict was missing the ``v``
    field — callers MUST increment a metric on this branch in loose mode.
    """

    request: RpcRequest | None
    reply: RpcReply | None
    legacy_envelope: bool


def is_legacy_envelope(payload: dict[str, Any]) -> bool:
    """Pre-decode probe: True iff the ``v`` field is absent.

    Useful for emitting metrics before invoking ``decode_*`` if the caller
    prefers a separate observation point. The same flag is also surfaced
    on ``DecodeResult.legacy_envelope`` after decode — use either, not both.
    """
    return "v" not in payload


def encode_request(req: RpcRequest) -> dict[str, Any]:
    """Serialise an RpcRequest to a JSON-safe dict.

    The returned dict is suitable for ``json.dumps`` and XADD via the
    ``{"payload": <json_str>}`` stream-entry shape.
    """
    return req.model_dump(mode="json")


def encode_reply(reply: RpcReply) -> dict[str, Any]:
    """Serialise an RpcReply to a JSON-safe dict.

    The returned dict is suitable for ``json.dumps`` and LPUSH onto the
    ``imperal:rpc:reply:{corr_id}`` reply list.
    """
    return reply.model_dump(mode="json")


def _missing_v_error(title: str, payload: dict[str, Any]) -> ValidationError:
    """Build a Pydantic-style ValidationError for missing ``v`` in strict mode.

    Done this way so callers handle a single exception type for all schema
    violations (see spec §7.2).
    """
    return ValidationError.from_exception_data(
        title=title,
        line_errors=[
            {
                "type": "missing",
                "loc": ("v",),
                "input": payload,
            }
        ],
    )


def decode_request(
    payload: dict[str, Any], *, strict_version: bool = False
) -> DecodeResult:
    """Validate a request dict from ``json.loads(stream_entry["payload"])``.

    Loose mode (default): missing ``v`` is treated as ``v=1``;
    ``DecodeResult.legacy_envelope`` reports True for caller observability.
    Strict mode: missing ``v`` raises ValidationError with ``loc=("v",)``.

    The caller's payload dict is never mutated.
    """
    legacy = is_legacy_envelope(payload)
    if legacy:
        if strict_version:
            raise _missing_v_error("RpcRequest", payload)
        payload = {**payload, "v": 1}
    return DecodeResult(
        request=RpcRequest.model_validate(payload),
        reply=None,
        legacy_envelope=legacy,
    )


def decode_reply(
    payload: dict[str, Any], *, strict_version: bool = False
) -> DecodeResult:
    legacy = is_legacy_envelope(payload)
    if legacy:
        if strict_version:
            raise _missing_v_error("RpcReply", payload)
        payload = {**payload, "v": 1}
    return DecodeResult(
        request=None,
        reply=RpcReply.model_validate(payload),
        legacy_envelope=legacy,
    )


def build_error_reply(
    *,
    corr_id: str,
    category: RpcErrorCategory,
    message: str,
    retryable: bool,
    worker_id: str,
    started_at_ns: int,
    finished_at_ns: int | None = None,
) -> RpcReply:
    """Construct a typed error reply.

    ``message`` is trimmed to 512 chars to respect I7 (reply ≤ 256KB cap)
    even when an extension stack-trace is exceptionally long.
    """
    return RpcReply(
        v=ENVELOPE_VERSION,
        corr_id=corr_id,
        status=RpcStatus.ERROR,
        result=None,
        worker_id=worker_id,
        started_at_ns=started_at_ns,
        finished_at_ns=finished_at_ns if finished_at_ns is not None else time.time_ns(),
        error=RpcError(category=category, message=message[:512], retryable=retryable),
    )


def should_cache_reply(reply: RpcReply) -> bool:
    """I9 idempotency cache policy.

    Cache success and deterministic-error replies; do NOT cache transient
    infra/timeout failures (they may succeed on retry and caching them
    would block recovery).
    """
    if reply.status == RpcStatus.SUCCESS:
        return True
    assert reply.error is not None, "ERROR status must carry RpcError"
    return reply.error.category in (
        RpcErrorCategory.APPLICATION,
        RpcErrorCategory.TENANT_MISMATCH,
        RpcErrorCategory.SCHEMA_VIOLATION,
    )
