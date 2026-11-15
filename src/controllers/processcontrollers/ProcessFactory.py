from ..BaseController import BaseController
from ..ProjectController import ProjectController
from .interface import ProcessedFile
from .ChatHandler import ChatHandler
from .TextHandler import TextHandler
from .PdfHandler import PdfHandler
from .WordHandler import WordHandler
from .RecordsHandler import RecordsHandler
import os
import logging
import zipfile
import aiofiles
from models import ProcessingEnum
from models.enums.AssetTypeEnum import AssetTypeEnum

logger = logging.getLogger("uvicorn.error")

DOCUMENT_DIR = "document"
RECORDS_DIR = "records"

AUDIO_EXTENSIONS = {
    ProcessingEnum.OPUS.value,
    ProcessingEnum.M4A.value,
    ProcessingEnum.MP3.value,
    ProcessingEnum.OGG.value,
    ProcessingEnum.WAV.value,
    ProcessingEnum.AAC.value,
}

DOCUMENT_EXTENSIONS = {
    ProcessingEnum.TXT.value,
    ProcessingEnum.PDF.value,
    ProcessingEnum.DOCX.value,
}

PROCESS_ALL = "all"


class ProcessFactory(BaseController):

    def __init__(self, project_id: str, stt_client=None):
        super().__init__()
        self.project_id = project_id
        self.project_path = ProjectController().get_project_path(project_id=project_id)
        self.stt_client = stt_client
        self.logger = logger
        self.process_extensions = self._normalize_extensions(
            self.app_settings.FILE_PROCESS_ALLOWED_TYPES
        )

    def get_file_extension(self, file_id: str):
        return os.path.splitext(file_id)[-1].lower()

    async def process_file(self, file_id: str, chunk_size: int = 100, overlap_size: int = 20, file_type: str = PROCESS_ALL):
        files = await self._files_to_process(file_id, file_type)
        chat_files = []
        other_files = []
        for stored_name, original_name in files:
            extension = os.path.splitext(original_name)[-1].lower()
            if extension == ProcessingEnum.TXT.value and ChatHandler.is_chat_file(original_name):
                chat_files.append((stored_name, original_name))
            else:
                other_files.append((stored_name, original_name))

        attachments = {}
        processed_files = []
        for stored_name, original_name in chat_files + other_files:
            handler = self._make_handler(stored_name, original_name, attachments)
            if handler is None:
                self.logger.info(f"Skipping unsupported file: {original_name}")
                continue

            documents = handler.load()
            chunks = handler.chunk(documents, chunk_size, overlap_size)
            file_path = self._stored_path(stored_name)
            processed_files.append(ProcessedFile(
                stored_name=stored_name,
                original_name=original_name,
                size=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                chunks=chunks,
                asset_type=self.file_kind(original_name),
            ))

        self.logger.info(f"Processed {file_id}: files={len(processed_files)}")
        return processed_files

    def _make_handler(self, stored_name: str, original_name: str, attachments: dict):
        extension = os.path.splitext(original_name)[-1].lower()
        file_path = self._stored_path(stored_name)
        common = {
            "file_path": file_path,
            "original_name": original_name,
            "attachments": attachments,
            "logger": self.logger,
            "stt_client": self.stt_client,
        }

        if extension == ProcessingEnum.TXT.value and ChatHandler.is_chat_file(original_name):
            self.logger.info(f"Chunking chat file: {original_name}")
            return ChatHandler(**common)
        if extension == ProcessingEnum.TXT.value:
            self.logger.info(f"Chunking document with LangChain: {original_name}")
            return TextHandler(**common)
        if extension == ProcessingEnum.PDF.value:
            self.logger.info(f"Chunking document with LangChain: {original_name}")
            return PdfHandler(**common)
        if extension == ProcessingEnum.DOCX.value:
            self.logger.info(f"Chunking document with LangChain: {original_name}")
            return WordHandler(**common)
        if extension in AUDIO_EXTENSIONS:
            self.logger.info(f"Chunking record file: {original_name}")
            return RecordsHandler(**common)
        return None

    async def _files_to_process(self, file_id: str, file_type: str):
        extension = self.get_file_extension(file_id)
        if extension != ProcessingEnum.ZIP.value:
            self.logger.info(f"Skipping unsupported file: {file_id}")
            return []
        try:
            return await self._extract_supported_files(file_id, file_type)
        except zipfile.BadZipFile as error:
            self.logger.error(f"Invalid zip file {file_id}: {error}")
            return []

    async def _extract_supported_files(self, file_id: str, file_type: str):
        project_dirs = ProjectController()
        project_dirs.get_project_subdir(self.project_id, DOCUMENT_DIR)
        project_dirs.get_project_subdir(self.project_id, RECORDS_DIR)

        zip_path = self._stored_path(file_id)
        extracted = []

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue

                original_name = os.path.basename(member.filename.replace("\\", "/"))
                kind = self.file_kind(original_name)
                if not self._selected(kind, file_type):
                    self.logger.info(f"Skipping zip member: {member.filename}")
                    continue

                category = RECORDS_DIR if kind == AssetTypeEnum.RECORD.value else DOCUMENT_DIR
                stored_name = await self._write_zip_member(zip_file, member, original_name, category)
                extracted.append((stored_name, original_name))

        self.logger.info(f"Extracted {len(extracted)} supported files from {file_id}")
        return extracted

    async def _write_zip_member(self, zip_file, member, original_name: str, category: str):
        subdir = ProjectController().get_project_subdir(self.project_id, category)
        stored_file = original_name
        dest_path = os.path.join(subdir, stored_file)
        suffix = 0
        while os.path.exists(dest_path):
            suffix += 1
            stored_file = f"{suffix}_{original_name}"
            dest_path = os.path.join(subdir, stored_file)

        batch_size = self.app_settings.FILE_DEFAULT_CHUNK_SIZE
        with zip_file.open(member, "r") as source:
            async with aiofiles.open(dest_path, "wb") as target:
                while batch := source.read(batch_size):
                    await target.write(batch)

        return f"{category}/{stored_file}"

    def file_kind(self, original_name: str):
        if not original_name:
            return None
        extension = os.path.splitext(original_name)[-1].lower()
        if extension not in self.process_extensions:
            return None
        if extension == ProcessingEnum.TXT.value and ChatHandler.is_chat_file(original_name):
            return AssetTypeEnum.CHAT.value
        if extension in AUDIO_EXTENSIONS:
            return AssetTypeEnum.RECORD.value
        if extension in DOCUMENT_EXTENSIONS:
            return AssetTypeEnum.DOCUMENT.value
        return None

    def _selected(self, kind: str, file_type: str):
        if kind is None:
            return False
        return file_type == PROCESS_ALL or file_type == kind

    def _stored_path(self, stored_name: str):
        parts = stored_name.replace("\\", "/").split("/")
        return os.path.join(self.project_path, *parts)

    @staticmethod
    def _normalize_extensions(extensions):
        normalized = set()
        for extension in extensions or []:
            value = str(extension).strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value = f".{value}"
            normalized.add(value)
        return normalized
