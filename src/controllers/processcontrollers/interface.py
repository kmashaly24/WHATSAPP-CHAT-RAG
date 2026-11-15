from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
import os
import re
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class Document:
    page_content: str
    metadata: dict


@dataclass
class ProcessedFile:
    stored_name: str
    original_name: str
    size: int
    chunks: list
    asset_type: str


class FileHandlerInterface(ABC):
    """Contract for one file type. Every handler must implement load() and chunk()."""

    def __init__(self, file_path: str, original_name: str, attachments: dict = None, logger=None, stt_client=None):
        self.file_path = file_path
        self.original_name = original_name
        self.attachments = attachments if attachments is not None else {}
        self.logger = logger or logging.getLogger("uvicorn.error")
        self.stt_client = stt_client

    @abstractmethod
    def load(self) -> list:
        pass

    @abstractmethod
    def chunk(self, documents: list, chunk_size: int, overlap_size: int) -> list:
        pass

    def _langchain_chunk(self, documents: list, chunk_size: int, overlap_size: int):
        if not chunk_size or chunk_size < 1:
            chunk_size = 100
        overlap_size = overlap_size or 0
        if overlap_size < 0 or overlap_size >= chunk_size:
            overlap_size = 0

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap_size,
        )
        return splitter.split_documents(documents)

    def _apply_attachment_metadata(self, documents: list):
        names = [
            self.original_name.lower(),
            re.sub(r"^\d+_", "", os.path.basename(self.original_name).lower()),
        ]
        info = next((self.attachments[name] for name in names if name in self.attachments), None)
        if not info:
            return
        for document in documents:
            metadata = dict(document.metadata or {})
            metadata["sender"] = info["sender"]
            metadata["datetime"] = info["datetime"]
            document.metadata = metadata
        self.logger.info(f"Attached sender metadata to {self.original_name}")
