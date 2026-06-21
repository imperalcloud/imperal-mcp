# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Structured error taxonomy (P2 task 19 — Federal-Grade Chat Integrity).

Purpose
-------
Replace ad-hoc ``str(exception)`` content that historically leaked into
user-visible writes (email bodies, note titles, SMS). Every kernel- or
SDK-side error that surfaces to an LLM tool_result MUST map to one of the
10 codes below; the corresponding i18n key drives the actual user-facing
copy via the platform's canonical response templates.

This module is *read-only data* — no logic, no fabrication surface.
Mirror at the platform narration mirror is kept byte-for-byte
compatible (enforced by ``scripts/validate_error_taxonomy.py`` in the
kernel).

Closes P0-4 ("raw exception strings bleeding into write-side tool args").

Invariants
----------
* Every entry has exactly ``user_hint_i18n_key`` + ``default_en`` + ``default_ru``.
* Every ``user_hint_i18n_key`` lives in the ``errors.*`` namespace.
* Defaults are generic (no PII, no host paths, no user tokens).
* SDK/kernel catalogs MUST match — enforced by
  ``test_sdk_kernel_catalogs_match`` in the kernel validator.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Public string constants (for ``from ... import VALIDATION_MISSING_FIELD``). #
# Values are equal to the dict keys — importers can pass either safely.       #
# --------------------------------------------------------------------------- #
VALIDATION_MISSING_FIELD = "VALIDATION_MISSING_FIELD"
VALIDATION_TYPE_ERROR = "VALIDATION_TYPE_ERROR"
FABRICATED_ID_SHAPE = "FABRICATED_ID_SHAPE"
UNKNOWN_TOOL = "UNKNOWN_TOOL"
UNKNOWN_SUB_FUNCTION = "UNKNOWN_SUB_FUNCTION"
PERMISSION_DENIED = "PERMISSION_DENIED"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_5XX = "BACKEND_5XX"
RATE_LIMITED = "RATE_LIMITED"
INTERNAL = "INTERNAL"


ERROR_TAXONOMY: dict[str, dict[str, str]] = {
    "VALIDATION_MISSING_FIELD": {
        "user_hint_i18n_key": "errors.validation.missing_field",
        "default_en": "A required field is missing: {fields}",
        "default_ru": "Отсутствует обязательное поле: {fields}",
    },
    "VALIDATION_TYPE_ERROR": {
        "user_hint_i18n_key": "errors.validation.type_error",
        "default_en": "Invalid value type for field: {field}",
        "default_ru": "Неверный тип значения для поля: {field}",
    },
    "FABRICATED_ID_SHAPE": {
        "user_hint_i18n_key": "errors.validation.fabricated_id_shape",
        "default_en": "The supplied id matches a known fabrication pattern; call inbox()/search()/folder() first to obtain a real id",
        "default_ru": "Идентификатор похож на сфабрикованный; сначала вызовите inbox()/search()/folder() и возьмите реальный id",
    },
    "UNKNOWN_TOOL": {
        "user_hint_i18n_key": "errors.dispatch.unknown_tool",
        "default_en": "Tool not available: {app_tool}",
        "default_ru": "Инструмент недоступен: {app_tool}",
    },
    "UNKNOWN_SUB_FUNCTION": {
        "user_hint_i18n_key": "errors.dispatch.unknown_sub_function",
        "default_en": "Sub-function not available: {name}",
        "default_ru": "Функция не найдена: {name}",
    },
    "PERMISSION_DENIED": {
        "user_hint_i18n_key": "errors.auth.permission_denied",
        "default_en": "Permission denied for this action",
        "default_ru": "Нет прав на это действие",
    },
    "BACKEND_TIMEOUT": {
        "user_hint_i18n_key": "errors.backend.timeout",
        "default_en": "The backend service timed out; please retry",
        "default_ru": "Бэкенд не ответил вовремя; попробуйте ещё раз",
    },
    "BACKEND_5XX": {
        "user_hint_i18n_key": "errors.backend.5xx",
        "default_en": "The backend service returned an error; please retry",
        "default_ru": "Бэкенд вернул ошибку; попробуйте ещё раз",
    },
    "RATE_LIMITED": {
        "user_hint_i18n_key": "errors.rate_limited",
        "default_en": "Too many requests; please slow down",
        "default_ru": "Слишком много запросов; попробуйте позже",
    },
    "INTERNAL": {
        "user_hint_i18n_key": "errors.internal",
        "default_en": "An internal error occurred",
        "default_ru": "Внутренняя ошибка",
    },
}


__all__ = [
    "ERROR_TAXONOMY",
    "VALIDATION_MISSING_FIELD",
    "VALIDATION_TYPE_ERROR",
    "FABRICATED_ID_SHAPE",
    "UNKNOWN_TOOL",
    "UNKNOWN_SUB_FUNCTION",
    "PERMISSION_DENIED",
    "BACKEND_TIMEOUT",
    "BACKEND_5XX",
    "RATE_LIMITED",
    "INTERNAL",
]
