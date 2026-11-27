"""Factory for selecting and instantiating BridgeCare AI providers."""

from typing import Optional

from ai_engine.providers.base import AIProvider
from ai_engine.providers.config import AIProviderConfig, AIProviderType
from ai_engine.providers.exceptions import ProviderConfigurationError
from ai_engine.providers.gemini import GeminiProvider
from ai_engine.providers.mock import MockProvider


def get_ai_provider(config: Optional[AIProviderConfig] = None) -> AIProvider:
    """Return an AIProvider instance based on BRIDGECARE_AI_PROVIDER.

    Supported values:
    - 'gemini': Uses GeminiProvider (requires GEMINI_API_KEY).
    - 'mock': Uses MockProvider (offline development).
    """
    cfg = config or AIProviderConfig()
    provider_name = (cfg.bridgecare_ai_provider or "").strip().lower()

    if provider_name == AIProviderType.GEMINI.value:
        return GeminiProvider(config=cfg)
    if provider_name == AIProviderType.MOCK.value:
        return MockProvider()

    raise ProviderConfigurationError(
        f"Unsupported BRIDGECARE_AI_PROVIDER: '{cfg.bridgecare_ai_provider}'. "
        "Supported values are 'gemini' and 'mock'.",
        provider=provider_name or "unknown",
    )
