"""Imperal SDK — RPC envelope contract package (W2).

See spec: ``docs/specs/2026-04-27-w2-pydantic-rpc-design.md`` (mirrored at
``superpowers/specs/`` in the workspace repo).

Public API is the union of contract.py and codec.py — import directly from
the package root:

    from imperal_sdk.rpc import (
        RpcRequest, RpcReply, RpcStatus, RpcError, RpcErrorCategory,
        encode_request, decode_request, encode_reply, decode_reply,
        build_error_reply, should_cache_reply,
        DecodeResult, ENVELOPE_VERSION,
    )
"""
from imperal_sdk.rpc.contract import (
    ENVELOPE_VERSION,
    RpcError,
    RpcErrorCategory,
    RpcReply,
    RpcRequest,
    RpcStatus,
)
from imperal_sdk.rpc.codec import (
    DecodeResult,
    build_error_reply,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
    is_legacy_envelope,
    should_cache_reply,
)

__all__ = [
    "ENVELOPE_VERSION",
    "RpcRequest",
    "RpcReply",
    "RpcStatus",
    "RpcError",
    "RpcErrorCategory",
    "DecodeResult",
    "encode_request",
    "encode_reply",
    "decode_request",
    "decode_reply",
    "is_legacy_envelope",
    "build_error_reply",
    "should_cache_reply",
]
