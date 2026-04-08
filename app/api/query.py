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

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, JSONResponse
from supabase import create_async_client
from app.models.schemas import QueryRequest, QueryResponse, SourceDocument
from app.core.config import settings
from app.core.embeddings import generate_embedding
import os
import json
import traceback
import logging
from groq import Groq as GroqClient

logging.basicConfig(level=logging.DEBUG)

router = APIRouter()

@router.post("/query")
async def query_documents(request: QueryRequest):
    try:
        # Decode user query with utf-8
        query_text = request.query.encode('utf-8', errors='ignore').decode('utf-8')

        # 1. Generate embedding for the query
        query_embedding = await generate_embedding(query_text)

        # 2. Connect to Supabase
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        # 3. Call the match_documents RPC function for cosine similarity search
        response = await supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.0,
                "match_count": request.top_k
            }
        ).execute()

        # 4. Format the response
        results = []
        context_texts = []
        if response.data:
            for row in response.data:
                content = row.get("content", "")
                context_texts.append(content)
                results.append(
                    {
                        "title": row.get("title", "Unknown"),
                        "content": content,
                        "similarity": row.get("similarity", 0.0),
                        "metadata": row.get("metadata", {})
                    }
                )

        # 5. Generate LLM answer
        context = "\n\n".join(context_texts)
        prompt = (
            "You are a helpful assistant for company documents. "
            "Answer ONLY based on the context provided below. "
            "If the answer is not in the context, say: 'I could not find this information in the uploaded documents.' "
            "Always respond in the same language as the question. "
            "Do not answer questions unrelated to the documents.\n\n"
            "Context:\n" + context + "\n\n"
            "Question: " + query_text
        )
        
        groq_client = GroqClient(api_key=settings.GROQ_API_KEY)
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = completion.choices[0].message.content
        answer = str(response_text).encode('utf-8', errors='ignore').decode('utf-8')

        data = {
            "query": query_text,
            "answer": answer,
            "results": results
        }

        return Response(
            content=json.dumps(data, ensure_ascii=False),
            media_type="application/json; charset=utf-8"
        )

    except Exception as e:
        full_trace = traceback.format_exc()
        logging.error(f"FULL ERROR: {full_trace}")
        return JSONResponse(
            content={"error": "An internal server error occurred.", "details": str(e)},
            status_code=500
        )
