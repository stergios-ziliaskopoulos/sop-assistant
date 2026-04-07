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
async def upload_file(file: UploadFile = File(...)):
    print(f"File received: {file.filename}", flush=True)
    print(f"Content-Type: {file.content_type}", flush=True)
    
    # Skip extraction, return success immediately
    return {"message": "Upload OK", "filename": file.filename}
