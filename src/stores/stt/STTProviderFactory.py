from .STTEnums import STTEnums
from .providers import FasterWhisperProvider
import logging

logger = logging.getLogger("uvicorn.error")


class STTProviderFactory:

    def __init__(self, config):
        self.config = config
        self.logger = logger

    def create(self, provider: str):
        if provider == STTEnums.WHISPER.value:
            return FasterWhisperProvider(
                model_size=self.config.WHISPER_MODEL_SIZE,
                device=self.config.WHISPER_DEVICE,
                compute_type=self.config.WHISPER_COMPUTE_TYPE,
                language=self.config.SPEECH_LANGUAGE,
            )

        self.logger.error(f"Unknown speech backend: {provider}")
        return None
