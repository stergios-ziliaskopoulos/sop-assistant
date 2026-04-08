import os
import sys
import locale
try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except Exception:
        pass
sys.stdout.reconfigure(encoding='utf-8')

from google import genai

def get_embedding_client():
    api_key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

async def generate_embedding(text: str) -> list[float]:
    query_text = text.encode('utf-8', errors='ignore').decode('utf-8')
    client = get_embedding_client()
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=query_text
    )
    return result.embeddings[0].values
