"""LLM Provider Abstraction — ICNLI Multi-Model Support.

Unified interface for LLM calls. Supports:
1. Anthropic (Claude) — default, zero-overhead native SDK
2. OpenAI-compatible API — OpenAI, Ollama, vLLM, llama.cpp, LM Studio, etc.
3. Google Gemini — via OpenAI-compatible API endpoint
4. Air-gapped mode — local models via openai_compatible + LLM_BASE_URL

Config resolution hierarchy (first wins):
  1. User BYOLLM  — ext_store __llm__ lookup, cached 60s
  2. Extension override  — Config Store imperal:config:llm → extensions.{app_id}
  3. Purpose override   — Config Store → purpose.{routing|execution|navigate}
  4. Global default     — Config Store → default, then ENV

ENV vars:
  LLM_PROVIDER=anthropic (default) | openai | openai_compatible | google
  LLM_API_KEY=...  (fallback: ANTHROPIC_API_KEY)
  LLM_MODEL=...
  LLM_BASE_URL=...
  LLM_ROUTING_MODEL=...
  LLM_EXECUTION_MODEL=...
  LLM_NAVIGATE_MODEL=...
  LLM_FALLBACK_PROVIDER=...
  LLM_FALLBACK_API_KEY=...
  LLM_FALLBACK_MODEL=...
  LLM_FALLBACK_BASE_URL=...
  IMPERAL_ENCRYPTION_KEY=... (fallback: IMAP_ENCRYPTION_KEY)
  REDIS_URL=...
  IMPERAL_GATEWAY_URL=...
  IMPERAL_SERVICE_TOKEN=...
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ENV config
# ---------------------------------------------------------------------------
_ENV_PROVIDER      = os.getenv("LLM_PROVIDER", "anthropic")
_ENV_API_KEY       = os.getenv("LLM_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
_ENV_MODEL         = os.getenv("LLM_MODEL", "")
_ENV_BASE_URL      = os.getenv("LLM_BASE_URL", "")
_ENV_ROUTING_MODEL = os.getenv("LLM_ROUTING_MODEL", "")
_ENV_EXEC_MODEL    = os.getenv("LLM_EXECUTION_MODEL", "")
_ENV_NAV_MODEL     = os.getenv("LLM_NAVIGATE_MODEL", "")

_ENV_FB_PROVIDER   = os.getenv("LLM_FALLBACK_PROVIDER", "")
_ENV_FB_API_KEY    = os.getenv("LLM_FALLBACK_API_KEY", "")
_ENV_FB_MODEL      = os.getenv("LLM_FALLBACK_MODEL", "")
_ENV_FB_BASE_URL   = os.getenv("LLM_FALLBACK_BASE_URL", "")


# OpenAI gpt-5 family + o-series reasoning models (o1/o3/o4) reject the
# legacy `max_tokens` kwarg with "'max_tokens' is not supported with this
# model. Use 'max_completion_tokens' instead." Other providers (Anthropic,
# Gemini via OpenAI-compat, Ollama/vLLM via openai_compatible) keep
# `max_tokens` — sending `max_completion_tokens` to them is unsafe.
#
# The same family also rejects any custom `temperature`: only the default
# (1.0) is supported, and sending e.g. `temperature=0.0` raises 400
# "'temperature' does not support 0.0 with this model. Only the default (1)
# value is supported." `_openai_supports_custom_temperature` gates that.
_OPENAI_MCT_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _openai_uses_max_completion_tokens(provider: str, model: str) -> bool:
    if provider != "openai" or not model:
        return False
    return model.lower().startswith(_OPENAI_MCT_MODEL_PREFIXES)


def _openai_supports_custom_temperature(provider: str, model: str) -> bool:
    """OpenAI gpt-5 + o-series reasoning models accept ONLY the default
    temperature (1.0). Sending `temperature=0.0` (or any other value)
    raises 400 'Unsupported value: temperature does not support X with
    this model. Only the default (1) value is supported.' Returns False
    for those models so callers know to omit the kwarg entirely.

    For all other provider/model combinations (other OpenAI models,
    Anthropic, Gemini, Ollama/vLLM via openai_compatible) custom
    temperature is supported and the helper returns True.
    """
    if provider != "openai" or not model:
        return True
    return not model.lower().startswith(_OPENAI_MCT_MODEL_PREFIXES)

_GATEWAY_URL       = os.getenv("IMPERAL_GATEWAY_URL", "")
_SERVICE_TOKEN     = os.getenv("IMPERAL_SERVICE_TOKEN", "")

# Default models per provider
_PROVIDER_DEFAULTS: dict[str, dict] = {
    "anthropic": {
        "model": "claude-haiku-4-5-20251001",
        "routing_model": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "model": "gpt-4o-mini",
        "routing_model": "gpt-4o-mini",
    },
    "openai_compatible": {
        "model": "llama3.1:8b",
        "routing_model": "llama3.1:8b",
    },
    "google": {
        "model": "gemini-2.0-flash",
        "routing_model": "gemini-2.0-flash",
    },
}

_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Config Store cache TTL (seconds)
_CONFIG_CACHE_TTL = 60
# BYOLLM cache TTL (seconds)
_BYOLLM_CACHE_TTL = 60


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

# LCU-7 (2026-04-30): provider-aware AI param filter, mirrors kernel.
# Each provider only accepts a subset of (temperature, max_tokens, top_p,
# presence_penalty, frequency_penalty, stop_sequences). Sending an
# unsupported param raises 400 from the upstream API. The filter ensures
# admin-set params silently drop on incompatible providers instead of
# breaking the call.
_PROVIDER_PARAM_SUPPORT: dict[str, set[str]] = {
    "anthropic": {"temperature", "max_tokens", "top_p", "stop_sequences"},
    "openai": {
        "temperature", "max_tokens", "top_p",
        "presence_penalty", "frequency_penalty", "stop_sequences",
    },
    "openai_compatible": {
        "temperature", "max_tokens", "top_p",
        "presence_penalty", "frequency_penalty", "stop_sequences",
    },
    "google": {"temperature", "max_tokens", "top_p", "stop_sequences"},
    "_default": {"temperature", "max_tokens"},
}

# OpenAI gpt-5 + o1/o3/o4 reasoning family rejects temperature/top_p/
# penalty params; only max_tokens (translated to max_completion_tokens by
# the existing adapter) is accepted.
_OPENAI_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_openai_reasoning_model(model: str) -> bool:
    if not model:
        return False
    m = model.lower()
    for prefix in _OPENAI_REASONING_MODEL_PREFIXES:
        if m.startswith(prefix):
            return True
    return False


def _supported_params_for(provider: str, model: str) -> set[str]:
    """Return the set of AI param names this provider/model accepts."""
    if provider == "openai" and _is_openai_reasoning_model(model):
        return {"max_tokens"}
    return _PROVIDER_PARAM_SUPPORT.get(provider, _PROVIDER_PARAM_SUPPORT["_default"])


@dataclass
class LLMConfig:
    """Resolved LLM configuration for a single call.

    Sprint 1.2 (2026-04-28): aligned field shape with
    the platform LLM config so kernel-built configs
    deserialize cleanly into SDK code via ctx._llm_configs injection.
    api_key is field(repr=False) — NEVER in default __repr__.

    LCU-7 (2026-04-30): added 6 AI param fields (temperature, max_tokens,
    top_p, presence_penalty, frequency_penalty, stop_sequences). All
    default to None which means "no admin override — let the provider
    apply its own default". The ``api_kwargs()`` method filters by
    provider via ``_supported_params_for`` so unsupported fields are
    silently dropped instead of triggering a 400.
    """
    provider: str
    model: str
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    is_byollm: bool = False
    byollm_fallback: str = "platform"  # "platform" or "error"
    thinking_mode: str = "auto"  # "auto", "off", "on"
    byollm_tool_choice: str = ""  # "", "auto", "required", "none"
    failover_config: "LLMConfig | None" = None  # Sprint 1.2: pre-resolved pair
    # LCU-7 (2026-04-30): AI params from admin slots (per-extension,
    # per-purpose, global cascade — kernel resolves and ctx-injects). None
    # = "no override; provider's own default applies". ``api_kwargs()``
    # filters by provider.
    temperature: "float | None" = None
    max_tokens: "int | None" = None
    top_p: "float | None" = None
    presence_penalty: "float | None" = None
    frequency_penalty: "float | None" = None
    stop_sequences: "list[str] | None" = None

    @property
    def client_key(self) -> str:
        """Stable key for client pool hashing."""
        key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()[:12]
        return f"{self.provider}:{self.base_url or 'default'}:{key_hash}"

    def api_kwargs(self) -> dict:
        """Return provider-filtered kwargs dict for create_message().

        LCU-7 (2026-04-30). Drops params not supported by current
        provider/model (e.g. ``presence_penalty`` for Anthropic). Drops
        ``None`` values — those mean "caller hasn't overridden + no admin
        slot — use provider's own default".
        """
        supported = _supported_params_for(self.provider, self.model)
        out: dict = {}
        candidates = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
            "stop_sequences": self.stop_sequences,
        }
        for name, value in candidates.items():
            if value is None:
                continue
            if name not in supported:
                continue
            out[name] = value
        return out


@dataclass
class LLMUsage:
    """Usage record for a single LLM call."""
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    is_byollm: bool = False
    is_failover: bool = False
    purpose: str = ""
    extension_id: str = ""
    user_id: str = ""
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _get_fernet():
    """Return a Fernet instance or None if key is unavailable."""
    key = os.getenv("IMPERAL_ENCRYPTION_KEY", "") or os.getenv("IMAP_ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        log.warning(f"LLMProvider: Fernet init failed: {e}")
        return None


def _decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string. Returns plaintext or original on error."""
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # already plaintext or bad key


def _encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string with Fernet. Returns ciphertext or original on error."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    try:
        return f.encrypt(plaintext.encode()).decode()
    except Exception:
        return plaintext


# ---------------------------------------------------------------------------
# LLMProvider — main class
# ---------------------------------------------------------------------------

class LLMProvider:
    """Multi-model LLM provider with config resolution, client pool, failover, usage tracking."""

    def __init__(self):
        # Legacy compat: expose provider_type / model / routing_model as attributes
        self.provider_type: str = _ENV_PROVIDER
        defaults = _PROVIDER_DEFAULTS.get(self.provider_type, _PROVIDER_DEFAULTS["anthropic"])
        self.model: str = _ENV_MODEL or defaults["model"]
        self.routing_model: str = _ENV_ROUTING_MODEL or defaults["routing_model"]

        # Client pool: client_key -> client instance
        self._client_pool: dict[str, Any] = {}

        # Per-action call log for LLM step tracking
        self._call_log: list[dict] = []

    # ------------------------------------------------------------------
    # Call log -- per-action LLM step tracking
    # ------------------------------------------------------------------

    def reset_call_log(self):
        self._call_log = []

    def get_call_log(self) -> list:
        return list(self._call_log)

    # ------------------------------------------------------------------
    # Standalone-SDK fallback — Sprint 1.2 contract
    # ------------------------------------------------------------------

    def _env_default_config_for_purpose(self, purpose: str) -> "LLMConfig":
        """Build an ENV-only LLMConfig for a given purpose. Sprint 1.2.

        Used as standalone-SDK fallback when ``ctx._llm_configs`` is None
        (extension developer running outside kernel, or kernel resolution
        failed). Reads:
          - LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY (global)
          - LLM_<PURPOSE>_MODEL (per-purpose override; e.g.
            LLM_EXECUTION_MODEL, LLM_ROUTING_MODEL, LLM_NAVIGATE_MODEL)
          - ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY
            (provider-specific keys when LLM_API_KEY is empty)
        """
        provider = os.getenv("LLM_PROVIDER", "anthropic")
        defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["anthropic"])
        # Per-purpose model override
        purpose_env_map = {
            "routing": os.getenv("LLM_ROUTING_MODEL", ""),
            "execution": os.getenv("LLM_EXECUTION_MODEL", ""),
            "navigate": os.getenv("LLM_NAVIGATE_MODEL", ""),
        }
        model = (
            purpose_env_map.get(purpose, "")
            or os.getenv("LLM_MODEL", "")
            or defaults["model"]
        )
        # API key — explicit LLM_API_KEY first, then provider-specific
        api_key = os.getenv("LLM_API_KEY", "")
        if not api_key:
            api_key = {
                "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
                "openai": os.getenv("OPENAI_API_KEY", ""),
                "google": os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", ""),
                "openai_compatible": os.getenv("LLM_API_KEY", ""),
            }.get(provider, "")
        return LLMConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", ""),
            is_byollm=False,
            byollm_fallback="platform",
        )

    # ------------------------------------------------------------------
    # Public API — preserved for all call sites
    # ------------------------------------------------------------------

    async def create_message(
        self,
        messages: list,
        system: str = "",
        max_tokens: int = 1024,
        *,
        cfg: "LLMConfig | None" = None,
        purpose: str = "",
        extension_id: str = "",
        user_id: str = "",
        tools: Optional[list] = None,
        tool_choice: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> Any:
        """Create a chat completion. Sprint 1.2 contract.

        Preferred: pass pre-resolved ``cfg=LLMConfig``. Kernel
        ``context_factory`` injects ``ctx._llm_configs[purpose]`` at
        ctx-build time; the SDK chat handler reads from there.

        Legacy: pass ``purpose=``+``user_id=`` (no ``cfg=``). Falls back
        to ENV-only resolution (no platform state store, no gateway HTTP) and emits a
        DEPRECATION warn once per process. Will be removed in SDK 4.0.0.

        Failover: when the primary call fails AND ``cfg.failover_config``
        is set, retry once with the pre-resolved failover config.
        """
        start_ms = int(time.monotonic() * 1000)

        # Legacy compat shim
        if cfg is None:
            if not getattr(self, "_legacy_create_warned", False):
                log.warning(
                    "create_message(purpose=, user_id=) is deprecated "
                    "(Sprint 1.2). Kernel-side ctx-injection is the "
                    "supported path; SDK chat handler reads cfg from "
                    "ctx._llm_configs. Legacy callers fall back to "
                    "ENV-only resolution. Will be removed in SDK 4.0.0."
                )
                self._legacy_create_warned = True
            cfg = self._env_default_config_for_purpose(purpose or "execution")

        # Log resolved config for visibility
        _byollm_tag = " [BYOLLM]" if cfg.is_byollm else ""
        _purpose_tag = f" purpose={purpose}" if purpose else ""
        _ext_tag = f" ext={extension_id}" if extension_id else ""
        log.info(f"LLM call: {cfg.provider}/{cfg.model}{_purpose_tag}{_ext_tag}{_byollm_tag}")

        # Track last call config for action_writer (executor reads this)
        self._last_call_info = {"provider": cfg.provider, "model": cfg.model}

        is_failover = False
        import time as _t; _call_start = _t.time()
        _call_error = None
        resp = None
        try:
            try:
                resp = await self._call(cfg, messages, system, max_tokens, tools, tool_choice, temperature)
            except Exception as primary_err:
                if cfg.failover_config is None:
                    _call_error = str(primary_err)[:200]
                    raise
                log.warning(
                    f"primary {cfg.provider}/{cfg.model} failed "
                    f"({type(primary_err).__name__}); failover to "
                    f"{cfg.failover_config.provider}/{cfg.failover_config.model}"
                )
                try:
                    resp = await self._call(cfg.failover_config, messages, system, max_tokens, tools, tool_choice, temperature)
                    cfg = cfg.failover_config
                    is_failover = True
                except Exception as fb_err:
                    log.error(
                        f"failover {cfg.failover_config.provider}/{cfg.failover_config.model} also failed: {fb_err}"
                    )
                    _call_error = str(fb_err)[:200]
                    raise fb_err
        finally:
            # ALWAYS append to call log — even on failure (for Activity visibility)
            _call_ms = int((_t.time() - _call_start) * 1000)
            _usage = getattr(resp, "usage", None) if resp is not None else None
            self._call_log.append({
                "purpose": purpose or "default",
                "provider": cfg.provider,
                "model": cfg.model,
                "input_tokens": getattr(_usage, "input_tokens", 0) if _usage else 0,
                "output_tokens": getattr(_usage, "output_tokens", 0) if _usage else 0,
                "latency_ms": _call_ms,
                "is_failover": is_failover,
                "error": _call_error,
            })

        return resp

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    def _env_default_config(self) -> LLMConfig:
        """Build LLMConfig from ENV vars."""
        provider = _ENV_PROVIDER
        defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["anthropic"])
        model = _ENV_MODEL or defaults["model"]
        base_url = _ENV_BASE_URL
        if provider == "google" and not base_url:
            base_url = _GOOGLE_BASE_URL
        return LLMConfig(
            provider=provider,
            model=model,
            api_key=_ENV_API_KEY,
            base_url=base_url,
        )

    def _config_from_store(self, cfg: dict) -> LLMConfig | None:
        """Build LLMConfig from a Config Store dict entry.

        Returns None if provider has no valid API key (prevents using wrong provider's key).
        """
        provider = cfg.get("provider", _ENV_PROVIDER)
        # Map Panel "custom" to openai_compatible
        if provider == "custom":
            provider = "openai_compatible"
        defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["anthropic"])
        model = cfg.get("model", "") or defaults["model"]

        # Resolve API key — ONLY use _ENV_API_KEY if provider matches ENV provider
        api_key = _decrypt(cfg.get("api_key", ""))
        if not api_key:
            # Check provider-specific ENV keys
            _provider_env_keys = {
                "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
                "openai": os.getenv("OPENAI_API_KEY", ""),
                "google": os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", ""),
                "openai_compatible": os.getenv("LLM_API_KEY", ""),
            }
            api_key = _provider_env_keys.get(provider, "")

            # Last resort: if provider matches ENV default provider, use generic LLM_API_KEY
            if not api_key and provider == _ENV_PROVIDER:
                api_key = _ENV_API_KEY

            if not api_key:
                log.warning(f"LLMProvider: no API key for provider '{provider}' — skipping config")
                return None

        base_url = cfg.get("base_url", "")
        # Inherit base_url from global config if purpose override doesn't specify one
        if not base_url and self._config_cache and isinstance(self._config_cache, dict):
            _global_provider = self._config_cache.get("provider", "")
            if _global_provider == "custom":
                _global_provider = "openai_compatible"
            if provider == _global_provider:
                base_url = self._config_cache.get("base_url", "")
        if provider == "google" and not base_url:
            base_url = _GOOGLE_BASE_URL
        return LLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)

    async def _call(self, cfg: LLMConfig, messages, system, max_tokens, tools, tool_choice, temperature) -> Any:
        """Dispatch to the correct provider backend."""
        if cfg.provider == "anthropic":
            return await self._call_anthropic(cfg, messages, system, max_tokens, tools, tool_choice, temperature)
        else:
            return await self._call_openai(cfg, messages, system, max_tokens, tools, tool_choice, temperature)

    async def _call_anthropic(self, cfg: LLMConfig, messages, system, max_tokens, tools, tool_choice, temperature) -> Any:
        """Native Anthropic SDK call — zero overhead."""
        client = self._get_client(cfg)
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            kwargs["temperature"] = temperature
        # LCU-7 (2026-04-30): apply admin-cascaded top_p / stop_sequences
        # via cfg.api_kwargs() (provider-filtered, drops unsupported fields
        # like presence/frequency_penalty for Anthropic). max_tokens and
        # temperature already resolved by the call_message caller with
        # caller-explicit precedence; setdefault preserves that.
        for _k, _v in cfg.api_kwargs().items():
            if _k in ("max_tokens", "temperature"):
                continue
            kwargs.setdefault(_k, _v)
        return await client.messages.create(**kwargs)

    async def _call_openai(self, cfg: LLMConfig, messages, system, max_tokens, tools, tool_choice, temperature) -> Any:
        """OpenAI-compatible call via MessageAdapter."""
        from imperal_sdk.runtime.message_adapter import MessageAdapter

        client = self._get_client(cfg)
        oai_messages = MessageAdapter.to_openai_messages(messages, system)
        _token_kwarg = (
            "max_completion_tokens"
            if _openai_uses_max_completion_tokens(cfg.provider, cfg.model)
            else "max_tokens"
        )
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            _token_kwarg: max_tokens,
            "messages": oai_messages,
        }
        if _openai_supports_custom_temperature(cfg.provider, cfg.model):
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = MessageAdapter.to_openai_tools(tools)
        if tool_choice:
            oai_tc = MessageAdapter.to_openai_tool_choice(tool_choice)
            if oai_tc is not None:
                kwargs["tool_choice"] = oai_tc
        # LCU-7 (2026-04-30): apply admin-cascaded top_p / penalty /
        # stop_sequences via cfg.api_kwargs() (provider-filtered; for
        # gpt-5/o-series the filter returns {"max_tokens"} only, so this
        # is a no-op for those models). max_tokens / temperature already
        # resolved with caller-explicit precedence above.
        for _k, _v in cfg.api_kwargs().items():
            if _k in ("max_tokens", "temperature"):
                continue
            kwargs.setdefault(_k, _v)

        if cfg.provider == "openai_compatible":
            # See kernel llm/provider.py — dual-param thinking disable for Ollama.
            # think=False is Ollama native /api/chat; ignored on /v1/chat/completions.
            # reasoning_effort="none" is OpenAI-standard, supported by Ollama >=0.6
            # via /v1 (see ollama/ollama#14820). Safe across real-OpenAI o1/o3.
            kwargs["extra_body"] = {"think": False, "reasoning_effort": "none"}
        resp = await client.chat.completions.create(**kwargs)
        return MessageAdapter.from_openai_response(resp, cfg.model)

    # ------------------------------------------------------------------
    # Client pool
    # ------------------------------------------------------------------

    def _get_client(self, cfg: LLMConfig) -> Any:
        """Get or create a client from the pool. Keyed by provider+base_url+api_key_hash."""
        key = cfg.client_key
        if key in self._client_pool:
            return self._client_pool[key]

        client = self._create_client(cfg)
        self._client_pool[key] = client
        return client

    def _create_client(self, cfg: LLMConfig) -> Any:
        """Create a new client for the given config."""
        if cfg.provider == "anthropic":
            import anthropic
            api_key = cfg.api_key or os.getenv("ANTHROPIC_API_KEY", "")
            return anthropic.AsyncAnthropic(api_key=api_key)

        # OpenAI / openai_compatible / google — all use AsyncOpenAI
        from openai import AsyncOpenAI
        base_url = cfg.base_url
        if cfg.provider == "google" and not base_url:
            base_url = _GOOGLE_BASE_URL
        elif cfg.provider in ("openai",) and not base_url:
            base_url = None  # Use OpenAI default
        elif cfg.provider == "openai_compatible" and not base_url:
            base_url = "http://localhost:11434/v1"

        kwargs: dict[str, Any] = {
            "api_key": cfg.api_key or "not-needed",
        }
        if base_url:
            kwargs["base_url"] = base_url
        # Explicit long timeout for openai_compatible (local BYOLLM like Ollama,
        # vLLM, llama.cpp) — OpenAI SDK default httpx Timeout(600s, connect=5s)
        # is theoretically enough, but intermediate per-read idle timeouts on
        # the transport (seen at ~30s on AsyncOpenAI default transport with
        # Ollama's partial-stream behaviour) caused false Connection error
        # retries on multi-round tool-use loops against heavy 27B+ models.
        # 300s read/write/connect covers DGX-class inference for large context.
        if cfg.provider == "openai_compatible":
            import httpx as _httpx_cli
            kwargs["timeout"] = _httpx_cli.Timeout(300.0, connect=10.0)
        return AsyncOpenAI(**kwargs)

    # ------------------------------------------------------------------
    # Available providers (for Panel endpoint)
    # ------------------------------------------------------------------

    def get_available_providers(self) -> list[dict]:
        """Return list of providers that have valid API keys configured.

        Used by Panel to show only actually available providers.
        """
        available = []
        _keys = {
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY", "")),
            "openai": bool(os.getenv("OPENAI_API_KEY", "")),
            "google": bool(os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")),
        }
        for provider, has_key in _keys.items():
            if has_key:
                defaults = _PROVIDER_DEFAULTS.get(provider, {})
                available.append({
                    "provider": provider,
                    "has_key": True,
                    "default_model": defaults.get("model", ""),
                    "routing_model": defaults.get("routing_model", ""),
                })
        return available

    # ------------------------------------------------------------------
    # Usage tracking (fire-and-forget)
    # ------------------------------------------------------------------

    async def _track_usage(self, usage: LLMUsage) -> None:
        """Write usage metrics to the platform state store. Fire-and-forget — never raises.

        Sprint 1.1 (2026-04-28): TEMPORARILY no-op'd with WARN-once. The
        previous body imported `shared_redis` (legacy module renamed to
        the platform state store during a kernel refactor) which silently
        ImportError'd on every LLM call since the rename. Telemetry has been
        broken for unknown duration. Sprint 1.2 architectural cleanup will
        restore tracking via kernel-side resolution + ctx-injection (or via
        a dedicated auth-gw `/v1/internal/llm-usage/track` endpoint).
        Tracked as follow-up SP1.1-USAGE-TRACK.
        """
        if not getattr(self, "_track_usage_warned", False):
            log.warning(
                "LLMProvider: usage tracking is temporarily disabled (Sprint 1.1 "
                "deferred SP1.1-USAGE-TRACK; kernel/SDK resolution refactor in "
                "Sprint 1.2 will restore it). LLMUsage records are dropped."
            )
            self._track_usage_warned = True

    # ------------------------------------------------------------------
    # Background invalidation listener
    # ------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_provider_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Get singleton LLM provider instance. API unchanged for all call sites."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = LLMProvider()
        log.info(
            f"LLM Provider initialized: {_provider_instance.provider_type}, "
            f"model={_provider_instance.model}"
        )
    return _provider_instance


def get_routing_model() -> str:
    """Get the model name to use for routing/classification."""
    return get_llm_provider().routing_model


def is_air_gapped() -> bool:
    """Check if running in air-gapped mode (local models, no external API calls)."""
    return _ENV_PROVIDER == "openai_compatible"
