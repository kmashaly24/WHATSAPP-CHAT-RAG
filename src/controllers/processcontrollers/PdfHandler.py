from .interface import FileHandlerInterface
from langchain_community.document_loaders import PyMuPDFLoader


class PdfHandler(FileHandlerInterface):

    def load(self):
        self.logger.info(f"Loading pdf file: {self.original_name}")
        documents = PyMuPDFLoader(self.file_path).load()
        self._apply_attachment_metadata(documents)
        return documents

    def chunk(self, documents: list, chunk_size: int, overlap_size: int):
        return self._langchain_chunk(documents, chunk_size, overlap_size)
