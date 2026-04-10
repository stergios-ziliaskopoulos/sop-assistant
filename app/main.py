import sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf8', buffering=1)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api import health, ingest, query, upload, documents, auth
from app.core.config import settings
import os

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade RAG system for company documents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://stergios-ziliaskopoulos.github.io",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def set_utf8_headers(request: Request, call_next):
    response = await call_next(request)
    # Be careful not to override content-type for all responses blindly (e.g. application/json).
    # But as requested, we apply it.
    if not response.headers.get("Content-Type"):
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    elif "charset" not in response.headers.get("Content-Type", ""):
        response.headers["Content-Type"] += "; charset=utf-8"
    return response

app.include_router(health.router, tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(query.router, prefix="/api/v1", tags=["query"])
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])

# Ensure static directory exists
os.makedirs("app/static", exist_ok=True)

# Mount static files at root
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
