from .interface import FileHandlerInterface
from langchain_community.document_loaders import TextLoader


class TextHandler(FileHandlerInterface):

    def load(self):
        self.logger.info(f"Loading text file: {self.original_name}")
        documents = TextLoader(self.file_path, encoding="utf-8").load()
        self._apply_attachment_metadata(documents)
        return documents

    def chunk(self, documents: list, chunk_size: int, overlap_size: int):
        return self._langchain_chunk(documents, chunk_size, overlap_size)
