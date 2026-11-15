from .interface import Document, FileHandlerInterface
import os
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("uvicorn.error")


class ChatHandler(FileHandlerInterface):
    """WhatsApp chat export: load messages, then chunk them by size and a one-hour gap."""

    CHAT_FILE_PREFIX = "whatsapp chat with"

    UNLOADED_TEXTS = {
        "this message was deleted",
        "you deleted this message",
        "image omitted",
        "video omitted",
        "audio omitted",
        "sticker omitted",
        "gif omitted",
        "document omitted",
        "media omitted",
        "contact card omitted",
        "<image omitted>",
        "<video omitted>",
        "<audio omitted>",
        "<sticker omitted>",
        "<gif omitted>",
        "<document omitted>",
        "<media omitted>",
        "<contact card omitted>",
        "missed voice call",
        "missed video call",
        "voice call",
        "video call",
        "null",
        "تم حذف هذه الرسالة",
        "لقد حذفت هذه الرسالة",
        "حذفت هذه الرسالة",
        "تم حذف الوسائط",
        "الوسائط محذوفة",
        "صورة محذوفة",
        "مقطع صوتي محذوف",
        "فيديو محذوف",
        "ملصق محذوف",
        "مستند محذوف",
        "جهة اتصال محذوفة",
        "مكالمة صوتية فائتة",
        "مكالمة فيديو فائتة",
        "مكالمة صوتية",
        "مكالمة فيديو",
    }

    FORMATS = (
        re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\]\s*(.*)$"),
        re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\s+-\s+(.*)$"),
    )

    @staticmethod
    def is_chat_file(original_name: str):
        name = re.sub(r"^\d+_", "", os.path.basename(original_name).lower())
        stem = os.path.splitext(name)[0]
        return stem == "chat" or name.startswith(ChatHandler.CHAT_FILE_PREFIX)

    @staticmethod
    def normalize(line: str):
        return (
            line.replace("\u200e", "")
            .replace("\u200f", "")
            .replace("\u202f", " ")
            .replace("\xa0", " ")
            .replace("\ufeff", "")
            .strip()
        )

    def load(self):
        with open(self.file_path, "r", encoding="utf-8-sig") as file:
            lines = file.readlines()

        pattern = self._detect_format(lines)
        if pattern is None:
            logger.error(f"Could not detect a chat format: {self.file_path}")
            return []

        messages = []
        current = None
        for raw_line in lines:
            line = self.normalize(raw_line)
            match = pattern.match(line)
            if match:
                if current is not None:
                    messages.append(current)
                sender, text = self._sender_and_text(match.group(2))
                current = {"datetime": match.group(1).strip(), "sender": sender, "text": text}
                continue
            if current is not None and line:
                current["text"] = (current["text"] + "\n" + line).strip()

        if current is not None:
            messages.append(current)

        source_name = os.path.basename(self.file_path)
        documents = []
        skipped = 0
        for message in messages:
            attached_name = self._attached_filename(message["text"])
            if attached_name:
                self.attachments[attached_name.lower()] = {
                    "sender": message["sender"],
                    "datetime": message["datetime"],
                }
                skipped += 1
                continue
            text = self._visible_text(message["text"])
            if not text:
                skipped += 1
                continue
            documents.append(Document(
                page_content=f"[{message['datetime']}] {message['sender']}: {text}",
                metadata={
                    "sender": message["sender"],
                    "datetime": message["datetime"],
                    "source": source_name,
                },
            ))

        self.logger.info(
            f"WhatsApp chat parsed: file={source_name} messages={len(documents)} unloaded={skipped}"
        )
        return documents

    def chunk(self, documents: list, chunk_size: int, overlap_size: int):
        if not chunk_size or chunk_size < 1:
            chunk_size = 100

        half_size = chunk_size // 2
        messages = []
        for document in documents:
            text = (document.page_content or "").strip()
            if len(text) <= 1:
                continue
            messages.append({
                "text": text,
                "datetime": self._parse_message_datetime((document.metadata or {}).get("datetime")),
            })

        chunks = []
        index = 0
        previous_message_text = None

        while index < len(messages):
            parts = []
            if previous_message_text:
                if len(previous_message_text) > half_size:
                    parts.append(previous_message_text[-half_size:])
                else:
                    parts.append(previous_message_text)

            parts.append(messages[index]["text"])
            included = [messages[index]]
            index += 1

            while index < len(messages) and len("\n".join(parts)) < chunk_size:
                previous = included[-1]
                candidate = messages[index]
                if not self._within_one_hour(previous["datetime"], candidate["datetime"]):
                    break
                if len("\n".join(parts)) + 1 + len(candidate["text"]) > chunk_size:
                    break
                parts.append(candidate["text"])
                included.append(candidate)
                index += 1

            page = "\n".join(parts).strip()
            if page:
                chunks.append(Document(page_content=page, metadata={}))
            previous_message_text = included[-1]["text"]

        self.logger.info(f"Chat split into chunks={len(chunks)} messages={len(messages)}")
        return chunks

    def _attached_filename(self, text: str):
        marker = "(file attached)"
        for line in (text or "").splitlines():
            cleaned = line.strip()
            if not cleaned.lower().endswith(marker):
                continue
            name = os.path.basename(cleaned[: -len(marker)].strip())
            return name or None
        return None

    def _visible_text(self, text: str):
        kept_lines = []
        for line in (text or "").splitlines():
            normalized = line.strip().lower()
            if not normalized or self._is_unloaded(normalized):
                continue
            kept_lines.append(line.strip())
        return "\n".join(kept_lines).strip()

    def _is_unloaded(self, normalized_line: str):
        if normalized_line in self.UNLOADED_TEXTS:
            return True
        if "omitted" in normalized_line or normalized_line.startswith("<attached:"):
            return True
        if normalized_line.endswith("(file attached)"):
            return True
        return False

    def _detect_format(self, lines):
        for raw_line in lines:
            line = self.normalize(raw_line)
            for pattern in self.FORMATS:
                if pattern.match(line):
                    return pattern
        return None

    def _sender_and_text(self, rest: str):
        rest = rest.strip()
        if ": " in rest:
            sender, text = rest.split(": ", 1)
            return sender.strip(), text.strip()
        return "system", rest

    def _parse_message_datetime(self, value: str):
        if not value:
            return None
        for fmt in ("%m/%d/%y, %I:%M:%S %p", "%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M:%S %p", "%m/%d/%Y, %I:%M %p"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        self.logger.warning(f"Could not parse chat datetime: {value}")
        return None

    def _within_one_hour(self, previous_dt: datetime, current_dt: datetime):
        if previous_dt is None or current_dt is None:
            return True
        return abs(current_dt - previous_dt) < timedelta(hours=1)
