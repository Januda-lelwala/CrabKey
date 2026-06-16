"""Models.dev registry integration — community database for providers and models.

Fetches from https://models.dev/api.json — 4000+ models across 100+ providers.
Provides:
  - Provider metadata: name, base URL, env vars
  - Model metadata: context window, max output, cost, capabilities
    (reasoning, tools, vision, audio), modalities, family, deprecation

Cache hierarchy:
  1. In-memory cache (< 1 hour old)
  2. Disk cache at ~/.config/crabkey/models_dev_cache.json
  3. Network fetch
  4. Stale disk cache on network failure

Ported from Hermes Agent's agents/models_dev.py pattern.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
_CACHE_TTL = 3600  # 1 hour

_memory_cache: dict[str, Any] = {}
_memory_cache_time: float = 0


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    """Full metadata for a single model from models.dev."""

    id: str
    name: str
    family: str
    provider_id: str

    # Capabilities
    reasoning: bool = False
    tool_call: bool = False
    attachment: bool = False          # vision / image input
    structured_output: bool = False
    open_weights: bool = False

    # Modalities
    input_modalities: Tuple[str, ...] = ()
    output_modalities: Tuple[str, ...] = ()

    # Limits
    context_window: int = 0
    max_output: int = 0

    # Cost (USD per million tokens)
    cost_input: float = 0.0
    cost_output: float = 0.0
    cost_cache_read: Optional[float] = None

    # Metadata
    knowledge_cutoff: str = ""
    status: str = ""    # "alpha" | "beta" | "deprecated" | ""

    def supports_vision(self) -> bool:
        return self.attachment or "image" in self.input_modalities

    def format_cost(self) -> str:
        if not (self.cost_input or self.cost_output):
            return "unknown"
        return f"${self.cost_input:.2f}/M in, ${self.cost_output:.2f}/M out"

    def format_capabilities(self) -> str:
        caps = []
        if self.reasoning:
            caps.append("reasoning")
        if self.tool_call:
            caps.append("tools")
        if self.supports_vision():
            caps.append("vision")
        if self.open_weights:
            caps.append("open weights")
        return ", ".join(caps) if caps else "basic"


@dataclass
class ProviderInfo:
    """Metadata for a provider from models.dev."""

    id: str
    name: str
    env: Tuple[str, ...]
    api: str
    doc: str = ""
    model_count: int = 0


# Hermes provider names → models.dev provider IDs
PROVIDER_TO_MODELS_DEV: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openrouter": "openrouter",
    "gemini": "google",
    "google": "google",
    "deepseek": "deepseek",
    "xai": "xai",
    "mistral": "mistral",
    "groq": "groq",
    "novita": "novita-ai",
    "nvidia": "nvidia",
    "huggingface": "huggingface",
    "ollama-cloud": "ollama-cloud",
    "local": "",  # no models.dev entry
}


# ── Disk cache ────────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    import os
    home = os.environ.get("CRABKEY_HOME") or str(Path.home() / ".config" / "crabkey")
    return Path(home) / "models_dev_cache.json"


def _load_disk_cache() -> dict[str, Any]:
    try:
        p = _cache_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("models.dev disk cache load failed: %s", exc)
    return {}


def _save_disk_cache(data: dict[str, Any]) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    except Exception as exc:
        logger.debug("models.dev disk cache save failed: %s", exc)


def _disk_cache_age() -> Optional[float]:
    try:
        p = _cache_path()
        if not p.exists():
            return None
        age = time.time() - p.stat().st_mtime
        return age if age >= 0 else None
    except Exception:
        return None


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_models_dev(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch models.dev registry. Cache hierarchy: memory → disk → network.

    Returns the full registry dict keyed by models.dev provider ID.
    Returns {} on total failure.
    """
    global _memory_cache, _memory_cache_time

    if not force_refresh and _memory_cache and (time.time() - _memory_cache_time) < _CACHE_TTL:
        return _memory_cache

    if not force_refresh:
        disk_age = _disk_cache_age()
        if disk_age is not None and disk_age < _CACHE_TTL:
            data = _load_disk_cache()
            if data:
                _memory_cache = data
                _memory_cache_time = time.time() - disk_age
                return _memory_cache

    try:
        import urllib.request
        req = urllib.request.Request(MODELS_DEV_URL, headers={"User-Agent": "crabkey"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if isinstance(data, dict) and data:
            _memory_cache = data
            _memory_cache_time = time.time()
            _save_disk_cache(data)
            return data
    except Exception as exc:
        logger.debug("models.dev network fetch failed: %s", exc)

    # Fall back to any available disk cache
    if not _memory_cache:
        _memory_cache = _load_disk_cache()
        if _memory_cache:
            _memory_cache_time = time.time() - _CACHE_TTL + 300  # 5-min grace TTL

    return _memory_cache


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_mdev_models(provider: str) -> Optional[dict[str, Any]]:
    mdev_id = PROVIDER_TO_MODELS_DEV.get(provider, provider)
    if not mdev_id:
        return None
    data = fetch_models_dev()
    pdata = data.get(mdev_id)
    if not isinstance(pdata, dict):
        return None
    models = pdata.get("models", {})
    return models if isinstance(models, dict) else None


def _find_model_entry(models: dict, model_id: str) -> Optional[dict]:
    entry = models.get(model_id)
    if isinstance(entry, dict):
        return entry
    lower = model_id.lower()
    for mid, m in models.items():
        if mid.lower() == lower and isinstance(m, dict):
            return m
    return None


def _parse_model_info(model_id: str, raw: dict, provider_id: str) -> ModelInfo:
    limit = raw.get("limit") or {}
    cost = raw.get("cost") or {}
    modalities = raw.get("modalities") or {}
    if not isinstance(modalities, dict):
        modalities = {}
    input_mods = modalities.get("input") or []
    output_mods = modalities.get("output") or []

    ctx = limit.get("context")
    out = limit.get("output")

    return ModelInfo(
        id=model_id,
        name=raw.get("name", "") or model_id,
        family=raw.get("family", "") or "",
        provider_id=provider_id,
        reasoning=bool(raw.get("reasoning", False)),
        tool_call=bool(raw.get("tool_call", False)),
        attachment=bool(raw.get("attachment", False)),
        structured_output=bool(raw.get("structured_output", False)),
        open_weights=bool(raw.get("open_weights", False)),
        input_modalities=tuple(input_mods) if isinstance(input_mods, list) else (),
        output_modalities=tuple(output_mods) if isinstance(output_mods, list) else (),
        context_window=int(ctx) if isinstance(ctx, (int, float)) and ctx > 0 else 0,
        max_output=int(out) if isinstance(out, (int, float)) and out > 0 else 0,
        cost_input=float(cost.get("input", 0) or 0),
        cost_output=float(cost.get("output", 0) or 0),
        cost_cache_read=float(cost["cache_read"]) if cost.get("cache_read") is not None else None,
        knowledge_cutoff=raw.get("knowledge", "") or "",
        status=raw.get("status", "") or "",
    )


# ── Public API ────────────────────────────────────────────────────────────────

def get_model_info(provider: str, model_id: str) -> Optional[ModelInfo]:
    """Get full model metadata from models.dev. Returns None if not found."""
    mdev_id = PROVIDER_TO_MODELS_DEV.get(provider, provider)
    models = _get_mdev_models(provider)
    if models is None:
        return None
    entry = _find_model_entry(models, model_id)
    if entry is None:
        return None
    return _parse_model_info(model_id, entry, mdev_id)


def list_agentic_models(provider: str) -> list[str]:
    """Return model IDs suitable for agentic (tool-calling) use."""
    import re
    _NOISE = re.compile(
        r"-tts\b|embedding|live-|-(preview|exp)-\d{2,4}[-_]|-image\b|-image-preview\b",
        re.IGNORECASE,
    )
    models = _get_mdev_models(provider)
    if models is None:
        return []
    return [
        mid for mid, entry in models.items()
        if isinstance(entry, dict) and entry.get("tool_call") and not _NOISE.search(mid)
    ]


def get_provider_info(provider_id: str) -> Optional[ProviderInfo]:
    """Get provider metadata from models.dev."""
    mdev_id = PROVIDER_TO_MODELS_DEV.get(provider_id, provider_id)
    if not mdev_id:
        return None
    data = fetch_models_dev()
    raw = data.get(mdev_id)
    if not isinstance(raw, dict):
        return None
    env = raw.get("env") or []
    models = raw.get("models") or {}
    return ProviderInfo(
        id=mdev_id,
        name=raw.get("name", "") or mdev_id,
        env=tuple(env) if isinstance(env, list) else (),
        api=raw.get("api", "") or "",
        doc=raw.get("doc", "") or "",
        model_count=len(models) if isinstance(models, dict) else 0,
    )
