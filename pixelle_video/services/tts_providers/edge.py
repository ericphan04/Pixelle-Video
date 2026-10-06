"""
Edge TTS Provider Implementation
Default free testing voice engine powered by Microsoft Edge TTS.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

from loguru import logger
from pixelle_video.services.tts_providers.base import BaseTTSProvider
from pixelle_video.utils.tts_util import edge_tts
from pixelle_video.tts_voices import speed_to_rate, EDGE_TTS_VOICES


class EdgeTTSProvider(BaseTTSProvider):
    """
    Edge TTS provider implementation.
    """

    @property
    def provider_name(self) -> str:
        return "edge-tts"

    async def generate_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        output_path: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Generate speech using Microsoft Edge TTS.
        """
        final_voice = voice or "vi-VN-NamMinhNeural" if "vi" in (voice or "") else (voice or "zh-CN-YunjianNeural")
        final_speed = speed if speed is not None else 1.2
        rate = speed_to_rate(final_speed)

        if not output_path:
            unique_id = uuid.uuid4().hex
            output_path = f"output/{unique_id}.mp3"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"EdgeTTSProvider: voice={final_voice}, speed={final_speed}x ({rate}) -> {output_path}")
        await edge_tts(
            text=text,
            voice=final_voice,
            rate=rate,
            output_path=output_path,
        )

        return output_path

    def list_voices(self) -> List[Dict[str, Any]]:
        """
        Return list of supported Edge TTS voices.
        """
        try:
            return list(EDGE_TTS_VOICES)
        except Exception:
            return []
