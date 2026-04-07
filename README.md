# SOP Assistant — RAG System

## Overview
A production-ready RAG (Retrieval-Augmented Generation) system for company documents.
Upload PDFs, DOCX, or TXT files and ask questions in natural language.

## Tech Stack
- **Backend:** FastAPI + Python
- **Embeddings:** Google Gemini (gemini-embedding-001, 3072 dims)
- **Vector DB:** Supabase (pgvector)
- **LLM:** Groq + Llama 3.1 8B Instant
- **Frontend:** Vanilla JS Chat UI
- **Infrastructure:** Docker + Docker Compose

## Features
- Document ingestion (PDF, DOCX, TXT)
- Semantic similarity search
- LLM-generated answers with source citations
- Document management (list + delete)
- Dark/Light mode UI

## Setup
1. Clone the repo
2. Copy `.env.example` to `.env` and fill in your keys
3. Run: `docker-compose up -d`
4. Open: `http://localhost:8000`

## API Endpoints
- `GET /health` — Health check
- `POST /api/v1/ingest` — Ingest text document
- `POST /api/v1/upload` — Upload file (PDF/DOCX/TXT)
- `POST /api/v1/query` — Query documents
- `GET /api/v1/documents` — List documents
- `DELETE /api/v1/documents/{title}` — Delete document

## Environment Variables
See `.env.example` for required keys.
