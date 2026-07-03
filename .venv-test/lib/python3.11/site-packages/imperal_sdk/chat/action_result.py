"""Backward compatibility — ActionResult now lives in imperal_sdk.types.action_result.

All imports from this module continue to work.
"""
from imperal_sdk.types.action_result import ActionResult

__all__ = ["ActionResult"]
