from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID

class IngestRequest(BaseModel):
    tenant_id: UUID
    title: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

class SourceDocument(BaseModel):
    title: str
    content: str
    similarity: float
    metadata: Optional[Dict[str, Any]] = None

class QueryResponse(BaseModel):
    query: str
    answer: str
    results: List[SourceDocument]
