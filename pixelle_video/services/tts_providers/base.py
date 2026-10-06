"""
Base TTS Provider Interface
Defines the contract for all text-to-speech providers in Pixelle-Video.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class BaseTTSProvider(ABC):
    """
    Abstract Base Class for Text-to-Speech (TTS) providers.
    Allows easy plug-and-play of custom, local, or third-party voice engines.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the TTS provider."""
        pass

    @abstractmethod
    async def generate_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        output_path: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Synthesize speech from text and save to output_path.
        
        Args:
            text: Text content to synthesize
            voice: Voice ID or speaker identifier
            speed: Speech speed multiplier (e.g. 1.0 = normal)
            output_path: Target audio file path (.mp3, .wav)
            **kwargs: Provider-specific options
            
        Returns:
            Path to the generated audio file
        """
        pass

    @abstractmethod
    def list_voices(self) -> List[Dict[str, Any]]:
        """
        List available voices for this provider.
        
        Returns:
            List of dicts containing voice metadata (id, name, gender, language)
        """
        pass
