from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator


# Auth
class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Documents
class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    description: Optional[str] = None
    category: Optional[str] = None
    parser: Optional[str] = None
    page_count: Optional[int] = None
    text_chars: Optional[int] = None
    ocr_used: bool = False
    status: str
    error_message: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "created_by", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v)


class DocumentList(BaseModel):
    items: List[DocumentOut]
    total: int


class DocumentCategoryList(BaseModel):
    categories: List[str]


class IngestionJobOut(BaseModel):
    id: str
    document_id: str
    task_id: Optional[str] = None
    status: str
    phase: str
    progress: int
    retry_count: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "document_id", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v)


class IngestionJobList(BaseModel):
    items: List[IngestionJobOut]
    total: int


# Chat
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "default"
    stream: bool = False
    temperature: Optional[float] = None


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    text: str
    score: float
    chunk_index: Optional[int] = None
    section_title: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    document_page_count: Optional[int] = None
    quote: Optional[str] = None
    reference: Optional[str] = None


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[dict]
    citations: List[Citation]


class GraphEntity(BaseModel):
    id: str
    name: str
    type: str


class GraphRelation(BaseModel):
    source: str
    target: str
    type: str
    properties: Optional[dict] = None


class GraphExploreResponse(BaseModel):
    entities: List[GraphEntity]
    relations: List[GraphRelation]


class CommunitySummaryOut(BaseModel):
    community_id: str
    summary: str
    entity_count: int
    relation_count: int
    updated_at: Optional[datetime] = None


class CommunitySummaryList(BaseModel):
    items: List[CommunitySummaryOut]
    total: int


# Query logs
class QueryLogOut(BaseModel):
    id: str
    source: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    query: str
    intent: Optional[str] = None
    reasoning: Optional[str] = None
    answer: Optional[str] = None
    citation_count: int = 0
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v) if v is not None else None


class QueryLogList(BaseModel):
    items: List[QueryLogOut]
    total: int
