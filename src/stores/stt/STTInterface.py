from abc import ABC, abstractmethod


class STTInterface(ABC):

    @abstractmethod
    def transcribe(self, file_path: str, language: str = None) -> str:
        pass
