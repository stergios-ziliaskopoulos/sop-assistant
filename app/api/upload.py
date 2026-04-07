import locale
try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except Exception:
        pass
import sys
sys.stdout.reconfigure(encoding='utf-8')

from fastapi import APIRouter, HTTPException, UploadFile, File
import fitz  # PyMuPDF
import docx
import io
import tempfile
import os

from app.api.ingest import chunk_text
from app.core.config import settings
from app.core.embeddings import generate_embedding
from supabase import create_async_client

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_path = None
    try:
        content = ""
        file_ext = file.filename.split(".")[-1].lower()
        
        file_bytes = await file.read()
        
        # Write to temporary file to process BEFORE text extraction
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as temp_file:
            temp_path = temp_file.name
            temp_file.write(file_bytes)

        # Force UTF-8 decoding
        with open(temp_path, 'rb') as f:
            raw_content = f.read().decode('utf-8', errors='ignore')
            
        if file_ext == "pdf":
            doc = fitz.open(temp_path)
            for page in doc:
                text = page.get_text()
                content += text + "\n"
                print(text, flush=True)
        elif file_ext == "docx":
            doc = docx.Document(temp_path)
            for para in doc.paragraphs:
                text = para.text
                content += text + "\n"
                print(text, flush=True)
        elif file_ext == "txt":
            content = raw_content
            text = content
            print(text, flush=True)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, DOCX, or TXT.")

        if not content.strip():
            return {"message": "success", "filename": file.filename, "chunks_processed": 0}

        chunks = chunk_text(content, chunk_size=1000, overlap=200)
        
        if not chunks:
            return {"message": "success", "filename": file.filename, "chunks_processed": 0}

        embeddings = [await generate_embedding(chunk) for chunk in chunks]

        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        records = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            records.append({
                "title": file.filename,
                "content": chunk,
                "embedding": embedding,
                "metadata": {"chunk_index": i, "source_type": "upload"}
            })
            
        await supabase.table("documents").insert(records).execute()
        
        return {"message": "success", "filename": file.filename, "chunks_processed": len(chunks)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
