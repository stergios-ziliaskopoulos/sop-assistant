from fastapi import APIRouter, HTTPException
from supabase import create_async_client
from app.models.schemas import IngestRequest
from app.core.config import settings
from app.core.embeddings import generate_embedding

router = APIRouter()

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Split text into chunks of `chunk_size` characters with `overlap` characters overlap.
    """
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        chunks.append(text[start:start + chunk_size])
        if start + chunk_size >= text_length:
            break
        start += chunk_size - overlap
        
    return chunks

@router.post("/ingest")
async def ingest_document(request: IngestRequest):
    try:
        # 1. Split content into chunks
        chunks = chunk_text(request.content, chunk_size=1000, overlap=200)
        
        if not chunks:
            return {"message": "success", "chunks_processed": 0}

        # 2. Generate embeddings
        embeddings = [await generate_embedding(chunk) for chunk in chunks]

        # 3. Insert each chunk + embedding into Supabase table "documents"
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        records = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            metadata = request.metadata.copy() if request.metadata else {}
            metadata["chunk_index"] = i
            
            records.append({
                "title": request.title,
                "content": chunk,
                "embedding": embedding,
                "metadata": metadata,
                "tenant_id": "5ad31d01-92e7-4386-8b49-c294afb61ce5"
            })
            
        # Execute batch insert
        await supabase.table("documents").insert(records).execute()
        
        return {"message": "success", "chunks_processed": len(chunks)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
