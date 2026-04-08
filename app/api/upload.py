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
from fastapi.responses import JSONResponse
import fitz  # PyMuPDF
import docx
import io
import tempfile
import os
import traceback
import logging

logging.basicConfig(level=logging.DEBUG)

from app.api.ingest import chunk_text
from app.core.config import settings
from app.core.embeddings import generate_embedding
from supabase import create_async_client

router = APIRouter()

async def detect_and_extract(file_bytes: bytes, filename: str, temp_path: str) -> str:
    content = ""
    if file_bytes[:4] == b'%PDF':
        doc = fitz.open(temp_path)
        for page in doc:
            text = page.get_text()
            content += text + "\n"
            print(text, flush=True)
    elif filename.lower().endswith('.docx'):
        doc = docx.Document(temp_path)
        for para in doc.paragraphs:
            text = para.text
            content += text + "\n"
            print(text, flush=True)
    else:
        # parse as plain text
        raw_content = file_bytes.decode('utf-8', errors='ignore')
        content = raw_content
        print(content, flush=True)
    return content

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_path = None
    try:
        file_bytes = await file.read()
        
        # Write to temporary file to process BEFORE text extraction
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(file_bytes)

        content = await detect_and_extract(file_bytes, file.filename, temp_path)

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
        full_trace = traceback.format_exc()
        logging.error(f"FULL ERROR: {full_trace}")
        return JSONResponse(
            content={"error": "An internal server error occurred.", "details": str(e)},
            status_code=500
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
