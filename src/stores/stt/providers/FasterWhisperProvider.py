from ..STTInterface import STTInterface
from faster_whisper import WhisperModel
import logging
import os

logger = logging.getLogger("uvicorn.error")


def _compat_av_open():
    """PyAV 19 removed metadata_errors; faster-whisper 1.2.1 still passes it."""
    import av

    if getattr(av.open, "_metadata_errors_compat", False):
        return
    try:
        major = int(str(av.__version__).split(".")[0])
    except ValueError:
        major = 0
    if major < 19:
        return

    original_open = av.open

    def open_without_removed_args(file, mode="r", **kwargs):
        kwargs.pop("metadata_errors", None)
        kwargs.pop("metadata_encoding", None)
        return original_open(file, mode=mode, **kwargs)

    open_without_removed_args._metadata_errors_compat = True
    av.open = open_without_removed_args


class FasterWhisperProvider(STTInterface):

    def __init__(self, model_size: str, device: str, compute_type: str, language: str = None):
        self.model_size = model_size or "base"
        self.device = device or "cpu"
        self.compute_type = compute_type or "int8"
        self.language = language
        self.logger = logger
        self.model = None

    def _get_model(self):
        if self.model is not None:
            return self.model
        self.logger.info(
            f"Loading faster-whisper model={self.model_size} device={self.device} compute_type={self.compute_type}"
        )
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        return self.model

    def transcribe(self, file_path: str, language: str = None) -> str:
        _compat_av_open()
        chosen = self._whisper_language(language or self.language)
        segments, info = self._get_model().transcribe(file_path, language=chosen)
        parts = []
        for segment in segments:
            text = (segment.text or "").strip()
            if text:
                parts.append(text)
        transcript = " ".join(parts).strip()
        detected = getattr(info, "language", None)
        self.logger.info(
            f"Transcribed {os.path.basename(file_path)} chars={len(transcript)} language={chosen or detected}"
        )
        return transcript

    @staticmethod
    def _whisper_language(language: str):
        if not language:
            return None
        code = language.strip().split("-")[0].split("_")[0].lower()
        return code or None
