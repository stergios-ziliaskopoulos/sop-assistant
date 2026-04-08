# SOP Assistant — Production-Ready RAG System

![SOP Assistant Demo](https://via.placeholder.com/800x400.png?text=Add+Screenshot+Here) *(Add your application screenshot here)*

## 📖 Overview
The **SOP Assistant** is a production-grade, intelligent Retrieval-Augmented Generation (RAG) system designed to provide instant, accurate answers based on your company's internal documents. By leveraging advanced semantic search and large language models (LLMs), it empowers users to query knowledge bases seamlessly in natural language.

Whether you need to extract policies from a PDF, procedures from a DOCX, or guidelines from a TXT file, the SOP Assistant finds the exact context and generates a cited, highly accurate response.

## 🚀 Tech Stack
This project is built with a modern, scalable, and highly performant tech stack:

- **Backend Framework:** FastAPI (Python) - *Asynchronous, fast, and robust*
- **Embeddings Model:** Google Gemini (`gemini-embedding-001`, 3072 dimensions)
- **Vector Database:** Supabase (PostgreSQL with `pgvector`)
- **Large Language Model (LLM):** Groq API (Llama 3.1 8B Instant) - *Ultra-fast inference*
- **Frontend UI:** Vanilla JavaScript / HTML / CSS - *Zero-dependency, clean, responsive chat interface*
- **Containerization:** Docker & Docker Compose - *Ready for cloud deployment*

## ✨ Features
- **Multi-Format Document Ingestion:** Supports drag-and-drop uploading for `.pdf` (via PyMuPDF), `.docx` (via python-docx), and `.txt` files.
- **Smart Chunking & Embedding:** Automatically splits large documents into semantic chunks with overlap to preserve context before generating dense vector embeddings.
- **Semantic Similarity Search:** Uses cosine similarity (`<=>`) in Supabase to instantly retrieve the most relevant document fragments.
- **LLM-Generated Answers:** Feeds the retrieved context to Llama 3.1 via Groq to generate conversational, context-aware, and strictly grounded answers.
- **Source Citations:** Transparently displays the exact document chunks and similarity scores used by the LLM to formulate the answer.
- **Document Management:** View uploaded documents, their chunk counts, upload dates, and delete them directly from the UI.
- **Modern UI/UX:** Features a sleek Chat Interface with native Dark/Light mode support.

## 🛠️ System Architecture (RAG Flow)
1. **Ingestion:** User uploads a document $\rightarrow$ Text is extracted $\rightarrow$ Text is chunked $\rightarrow$ Chunks are embedded via Gemini API $\rightarrow$ Vectors are stored in Supabase.
2. **Retrieval:** User asks a question $\rightarrow$ Question is embedded via Gemini API $\rightarrow$ Supabase performs a vector similarity search $\rightarrow$ Top-K context chunks are returned.
3. **Generation:** Context + Question are injected into a strict prompt $\rightarrow$ Groq LLM generates the final answer $\rightarrow$ Answer + Sources are sent to the UI.

---

## ⚙️ Setup & Installation

### 1. Prerequisites
- Docker & Docker Compose installed on your machine.
- A [Supabase](https://supabase.com/) project.
- A [Google Gemini API Key](https://aistudio.google.com/).
- A [Groq API Key](https://console.groq.com/keys).

### 2. Database Setup (Supabase)
Before running the application, you must configure your Supabase PostgreSQL database to handle vector embeddings. 

Run the following SQL commands in your Supabase SQL Editor:

```sql
-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the documents table
CREATE TABLE IF NOT EXISTS documents (
  id BIGSERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding vector(3072),
  metadata JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create the similarity search RPC function
CREATE OR REPLACE FUNCTION match_documents (
  query_embedding vector(3072),
  match_threshold float,
  match_count int
)
RETURNS TABLE (
  title text,
  content text,
  similarity float,
  metadata jsonb
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    documents.title,
    documents.content,
    1 - (documents.embedding <=> query_embedding) AS similarity,
    documents.metadata
  FROM documents
  WHERE 1 - (documents.embedding <=> query_embedding) > match_threshold
  ORDER BY documents.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
```

### 3. Local Environment Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/sop-assistant.git
   cd sop-assistant
   ```
2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and fill in your actual API keys and Supabase connection details.

### 4. Run the Application
Start the application using Docker Compose:
```bash
docker-compose up -d --build
```
Once the containers are running, open your browser and navigate to:
**👉 `http://localhost:8000`**

---

## 📡 API Endpoints Reference
The backend provides a fully documented REST API (accessible via `/docs` when running). Core endpoints include:

- `GET /health` — API Health check.
- `POST /api/v1/upload` — Upload and process a file (`multipart/form-data`).
- `POST /api/v1/ingest` — Raw text ingestion endpoint.
- `POST /api/v1/query` — Submit a question and receive an LLM answer with sources.
- `GET /api/v1/documents` — List all documents currently stored in the vector database.
- `DELETE /api/v1/documents/{title}` — Remove a document and all its associated vector chunks.

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page.
