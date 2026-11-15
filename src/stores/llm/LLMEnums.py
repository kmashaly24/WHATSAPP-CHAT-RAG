from enum import Enum

class LLMEnums(Enum):
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"

class LLMRoleEnum(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

class DocumentTypeEnum(Enum):
    DOCUMENT = "document"
    QUERY = "query"
