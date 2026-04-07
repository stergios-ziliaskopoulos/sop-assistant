from fastapi import APIRouter, HTTPException, UploadFile, File
import fitz  # PyMuPDF
import docx
import io
import sys

# Ensure stdout uses UTF-8 to prevent encoding errors
sys.stdout.reconfigure(encoding='utf-8')

from app.api.ingest import chunk_text
from app.core.config import settings
from app.core.embeddings import generate_embedding
from supabase import create_async_client

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        content = ""
        file_ext = file.filename.split(".")[-1].lower()
        
        # Read file bytes
        file_bytes = await file.read()
        
        if file_ext == "pdf":
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                content += page.get_text() + "\n"
        elif file_ext == "docx":
            doc = docx.Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                content += para.text + "\n"
        elif file_ext == "txt":
            content = file_bytes.decode("utf-8")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, DOCX, or TXT.")

        if not content.strip():
            return {"message": "success", "filename": file.filename, "chunks_processed": 0}

        # 1. Split content into chunks
        chunks = chunk_text(content, chunk_size=1000, overlap=200)
        
        if not chunks:
            return {"message": "success", "filename": file.filename, "chunks_processed": 0}

        # 2. Generate embeddings
        embeddings = [await generate_embedding(chunk) for chunk in chunks]

        # 3. Insert each chunk + embedding into Supabase table "documents"
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        records = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            records.append({
                "title": file.filename,
                "content": chunk,
                "embedding": embedding,
                "metadata": {"chunk_index": i, "source_type": "upload"}
            })
            
        # Execute batch insert
        await supabase.table("documents").insert(records).execute()
        
        return {"message": "success", "filename": file.filename, "chunks_processed": len(chunks)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
