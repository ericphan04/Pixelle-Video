"""
TTS Providers registry and exports
"""

from typing import Dict, Type
from pixelle_video.services.tts_providers.base import BaseTTSProvider
from pixelle_video.services.tts_providers.edge import EdgeTTSProvider

_PROVIDERS: Dict[str, BaseTTSProvider] = {
    "edge": EdgeTTSProvider(),
    "edge-tts": EdgeTTSProvider(),
    "local": EdgeTTSProvider(),
}


def get_tts_provider(name: str = "edge") -> BaseTTSProvider:
    """Get TTS provider instance by name."""
    provider = _PROVIDERS.get(name.lower())
    if not provider:
        raise ValueError(f"Unknown TTS provider: '{name}'. Available: {list(_PROVIDERS.keys())}")
    return provider


def register_tts_provider(name: str, provider: BaseTTSProvider | Type[BaseTTSProvider]):
    """Register custom TTS provider instance or class."""
    if isinstance(provider, type):
        _PROVIDERS[name.lower()] = provider()
    else:
        _PROVIDERS[name.lower()] = provider


__all__ = ["BaseTTSProvider", "EdgeTTSProvider", "get_tts_provider", "register_tts_provider"]
