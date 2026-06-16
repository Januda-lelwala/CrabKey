"""Provider profile registry with plugin-based discovery.

Provider profiles live in two places:

1. Bundled plugins: ``crabkey/plugins/model-providers/<name>/``
2. User plugins: ``~/.config/crabkey/plugins/model-providers/<name>/``

Each plugin directory contains:
  - ``__init__.py`` — calls ``register_provider(profile)`` at import
  - ``plugin.yaml`` — manifest (name, kind, version, description)

Discovery is lazy: first call to ``get_provider_profile()`` or
``list_providers()`` scans both locations and imports every plugin.
User plugins override bundled plugins on name collision (last-writer-wins).

Ported from Hermes Agent's providers/__init__.py pattern.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from .profile import OMIT_TEMPERATURE, ProviderProfile  # noqa: F401

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, ProviderProfile] = {}
_ALIASES: dict[str, str] = {}
_discovered = False

# Bundled plugins directory: crabkey/plugins/model-providers/
# __file__ = crabkey/mal/provider_registry.py → .parent.parent = crabkey/
_BUNDLED_PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins" / "model-providers"


def register_provider(profile: ProviderProfile) -> None:
    """Register a provider profile by name and aliases.

    Later registrations with the same name replace earlier ones — user
    plugins can override bundled profiles without editing repo code.
    """
    _REGISTRY[profile.name] = profile
    for alias in profile.aliases:
        _ALIASES[alias] = profile.name


def get_provider_profile(name: str) -> ProviderProfile | None:
    """Look up a provider profile by name or alias. Returns None if not found."""
    if not _discovered:
        _discover_providers()
    canonical = _ALIASES.get(name, name)
    return _REGISTRY.get(canonical)


def list_providers() -> list[ProviderProfile]:
    """Return all registered provider profiles (one per canonical name)."""
    if not _discovered:
        _discover_providers()
    seen: set[int] = set()
    result: list[ProviderProfile] = []
    for profile in _REGISTRY.values():
        pid = id(profile)
        if pid not in seen:
            seen.add(pid)
            result.append(profile)
    return result


def _user_plugins_dir() -> Path | None:
    """Return ``~/.config/crabkey/plugins/model-providers/`` if it exists."""
    import os
    config_home = os.environ.get("CRABKEY_HOME") or str(Path.home() / ".config" / "crabkey")
    d = Path(config_home) / "plugins" / "model-providers"
    return d if d.is_dir() else None


def _import_plugin_dir(plugin_dir: Path, source: str) -> None:
    """Import a single plugin directory so it self-registers."""
    init_file = plugin_dir / "__init__.py"
    if not init_file.exists():
        return

    safe_name = plugin_dir.name.replace("-", "_")
    if source == "bundled":
        module_name = f"crabkey.plugins.model_providers.{safe_name}"
    else:
        module_name = f"_crabkey_user_provider_{safe_name}"

    if module_name in sys.modules:
        return

    try:
        spec = importlib.util.spec_from_file_location(
            module_name, init_file, submodule_search_locations=[str(plugin_dir)]
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("Failed to load %s provider plugin %s: %s", source, plugin_dir.name, exc)
        sys.modules.pop(module_name, None)


def _discover_providers() -> None:
    """Populate the registry by importing every provider plugin.

    Order:
      1. Bundled plugins at ``crabkey/plugins/model-providers/<name>/``
      2. User plugins at ``~/.config/crabkey/plugins/model-providers/<name>/``

    Later steps win on name collision (user > bundled).
    """
    global _discovered
    if _discovered:
        return
    _discovered = True

    # Ensure transports are registered before any plugin imports them.
    import crabkey.mal.transports  # noqa: F401

    if _BUNDLED_PLUGINS_DIR.is_dir():
        for child in sorted(_BUNDLED_PLUGINS_DIR.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            _import_plugin_dir(child, "bundled")

    user_dir = _user_plugins_dir()
    if user_dir is not None:
        for child in sorted(user_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            _import_plugin_dir(child, "user")
