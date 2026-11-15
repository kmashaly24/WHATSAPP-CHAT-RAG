from .interface import Document, FileHandlerInterface
from helpers.config import get_settings


class RecordsHandler(FileHandlerInterface):
    """Transcribes one audio record, then chunks that transcript on its own."""

    def load(self):
        if self.stt_client is None:
            self.logger.error(f"No speech client configured for {self.original_name}")
            return []

        language = get_settings().SPEECH_LANGUAGE
        self.logger.info(f"Transcribing record: {self.original_name} language={language}")
        try:
            text = self.stt_client.transcribe(self.file_path, language=language)
        except Exception as error:
            self.logger.error(f"Failed to transcribe {self.original_name}: {error}")
            return []

        text = (text or "").strip()
        if not text:
            self.logger.info(f"No speech recognized in {self.original_name}")
            return []

        documents = [Document(
            page_content=text,
            metadata={"source": self.original_name},
        )]
        self._apply_attachment_metadata(documents)
        return documents

    def chunk(self, documents: list, chunk_size: int, overlap_size: int):
        if not documents:
            return []
        return self._langchain_chunk(documents, chunk_size, overlap_size)
