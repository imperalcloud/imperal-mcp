"""SDK prompt template loader."""
from __future__ import annotations
from pathlib import Path

_DIR = Path(__file__).parent
_cache: dict[str, str] = {}


def load_prompt(name: str) -> str:
    """Load an SDK prompt template by filename. Cached."""
    if name not in _cache:
        _cache[name] = (_DIR / name).read_text(encoding="utf-8")
    return _cache[name]
