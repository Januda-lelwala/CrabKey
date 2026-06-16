from .message import CompletionResponse, Message, Role, ToolCall, ToolResult, Usage
from .provider import ModelConfig, ModelProvider, ToolSchema

# Profile + transport layer (Hermes-style plugin architecture)
from .profile import ProviderProfile, OMIT_TEMPERATURE
# Import transports eagerly so register_transport() calls fire at package load time.
from . import transports as _transports  # noqa: F401
from .transport import (
    ProviderTransport, NormalizedResponse, NormalizedToolCall, NormalizedUsage,
    register_transport, get_transport, list_api_modes,
)
from .provider_registry import (
    register_provider, get_provider_profile, list_providers,
)
from .plugin_provider import PluginModelProvider
from .model_catalog import (
    ModelInfo, ProviderInfo, get_model_info, list_agentic_models,
    get_provider_info, fetch_models_dev,
)

# Legacy adapters — kept for backward compatibility
from .adapters import AnthropicAdapter, LocalAdapter, OpenAIAdapter, OpenRouterAdapter

__all__ = [
    # Core message types
    "CompletionResponse", "Message", "Role", "ToolCall", "ToolResult", "Usage",
    # Provider ABC
    "ModelConfig", "ModelProvider", "ToolSchema",
    # Profile layer
    "ProviderProfile", "OMIT_TEMPERATURE",
    # Transport layer
    "ProviderTransport", "NormalizedResponse", "NormalizedToolCall", "NormalizedUsage",
    "register_transport", "get_transport", "list_api_modes",
    # Registry
    "register_provider", "get_provider_profile", "list_providers",
    # Plugin-backed concrete provider
    "PluginModelProvider",
    # Model catalog
    "ModelInfo", "ProviderInfo", "get_model_info", "list_agentic_models",
    "get_provider_info", "fetch_models_dev",
    # Legacy adapters
    "AnthropicAdapter", "OpenAIAdapter", "OpenRouterAdapter", "LocalAdapter",
]

