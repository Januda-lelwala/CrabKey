"""Shared fixtures for CrabKey tests."""

import sys
import pytest
import crabkey.mal.provider_registry as _reg

# Plugin module name prefix used by _import_plugin_dir
_PLUGIN_MODULE_PREFIX = "crabkey.plugins.model_providers."


@pytest.fixture(autouse=True)
def reset_provider_registry():
    """Reset the global provider registry and discovery flag between tests.

    Also evicts plugin modules from sys.modules so that re-discovery re-executes
    register_provider() calls rather than returning early on cached imports.
    """
    original_registry = dict(_reg._REGISTRY)
    original_aliases = dict(_reg._ALIASES)
    original_discovered = _reg._discovered

    yield

    # Evict cached plugin modules so the next discovery re-imports them
    for key in list(sys.modules):
        if key.startswith(_PLUGIN_MODULE_PREFIX) or key == "_crabkey_user_provider_local":
            del sys.modules[key]

    _reg._REGISTRY.clear()
    _reg._REGISTRY.update(original_registry)
    _reg._ALIASES.clear()
    _reg._ALIASES.update(original_aliases)
    _reg._discovered = original_discovered
