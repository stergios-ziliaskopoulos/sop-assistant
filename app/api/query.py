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

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response, JSONResponse
from supabase import create_async_client
from app.models.schemas import QueryRequest, QueryResponse, SourceDocument
from app.core.config import settings
from app.core.embeddings import generate_embedding
from app.core.auth import get_current_user
from pydantic import BaseModel, EmailStr
import os
import json
import time
import httpx
import traceback
import logging
from groq import Groq as GroqClient

logging.basicConfig(level=logging.DEBUG)

router = APIRouter()

DEMO_TENANT_ID = "5ad31d01-92e7-4386-8b49-c294afb61ce5"
DEMO_RATE_LIMIT = 10
DEMO_RATE_WINDOW = 3600  # 1 hour in seconds
_demo_rate_store: dict[str, list[float]] = {}

HANDOFF_PHRASES = [
    "i could not find",
    "i don't know",
    "not in the documents",
    "cannot find information",
    "couldn't find",
    "could not find this information",
    "not in the context",
]


def _needs_handoff(answer: str) -> bool:
    answer_lower = answer.lower()
    return any(phrase in answer_lower for phrase in HANDOFF_PHRASES)


class HandoffRequest(BaseModel):
    email: EmailStr
    question: str
    chat_context: str

@router.post("/query")
async def query_documents(request: QueryRequest, user=Depends(get_current_user)):
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
                "match_count": request.top_k,
                "filter_tenant_id": user.id,
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


def _check_demo_rate_limit(ip: str):
    now = time.time()
    timestamps = _demo_rate_store.get(ip, [])
    timestamps = [t for t in timestamps if now - t < DEMO_RATE_WINDOW]
    _demo_rate_store[ip] = timestamps
    if len(timestamps) >= DEMO_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Demo rate limit exceeded. Max 10 requests per hour.",
        )
    timestamps.append(now)


@router.post("/demo/query")
async def demo_query(request: QueryRequest, req: Request):
    client_ip = req.client.host if req.client else "unknown"
    _check_demo_rate_limit(client_ip)

    try:
        query_text = request.query.encode('utf-8', errors='ignore').decode('utf-8')

        query_embedding = await generate_embedding(query_text)

        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

        response = await supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.0,
                "match_count": request.top_k,
                "filter_tenant_id": DEMO_TENANT_ID,
            }
        ).execute()

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

        handoff = _needs_handoff(answer)
        data = {
            "query": query_text,
            "answer": answer,
            "sources": results,
            "needs_handoff": handoff,
        }
        if handoff:
            data["handoff_message"] = (
                "I couldn't find this in our docs. "
                "Can I get your email so our team can help you directly?"
            )

        return Response(
            content=json.dumps(data, ensure_ascii=False),
            media_type="application/json; charset=utf-8"
        )

    except HTTPException:
        raise
    except Exception as e:
        full_trace = traceback.format_exc()
        logging.error(f"FULL ERROR: {full_trace}")
        return JSONResponse(
            content={"error": "An internal server error occurred.", "details": str(e)},
            status_code=500
        )


@router.post("/demo/handoff")
async def demo_handoff(request: HandoffRequest, req: Request):
    client_ip = req.client.host if req.client else "unknown"
    _check_demo_rate_limit(client_ip)

    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        await supabase.table("handoff_requests").insert({
            "email": request.email,
            "question": request.question,
            "chat_context": request.chat_context,
            "status": "pending",
        }).execute()

        if settings.RESEND_API_KEY:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": "onboarding@resend.dev",
                        "to": ["szilias@gmail.com"],
                        "subject": "FirstLine AI - Human needed",
                        "text": (
                            f"Customer email: {request.email}\n"
                            f"Question: {request.question}\n"
                            f"Chat context: {request.chat_context}"
                        ),
                    },
                )

        return {"status": "ok", "message": "Our team will contact you shortly"}

    except HTTPException:
        raise
    except Exception as e:
        full_trace = traceback.format_exc()
        logging.error(f"FULL ERROR: {full_trace}")
        return JSONResponse(
            content={"error": "An internal server error occurred.", "details": str(e)},
            status_code=500
        )
