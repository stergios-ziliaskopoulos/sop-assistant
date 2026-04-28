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
from typing import Optional, List
import uuid
import os
import re
import json
import time
import httpx
import asyncio
import traceback
import logging
from groq import Groq as GroqClient
from app.services.slack_notifier import notify_handoff

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
    "i don't have a reliable answer for this in our documentation.",
]


CONFIDENCE_LOW = 0.50
CONFIDENCE_HIGH = 0.65

CONSERVATIVE_PROMPT = (
    "You are a strict documentation-only support agent. "
    "Answer ONLY using the exact content in the context below. "
    "Preface your answer with: 'Based on the closest information I found:' "
    "Always cite which document section your answer comes from. "
    "Always respond in the same language as the question. "
    "If the user asks for a SPECIFIC value, number, timeframe, or detail "
    "that is NOT explicitly present in the context, output ONLY: INSUFFICIENT_CONTEXT "
    "A partial match is NOT sufficient. Do NOT speculate. Do NOT say 'I am not confident'. "
    "Do NOT say 'it is possible'. If the exact answer is not there: INSUFFICIENT_CONTEXT\n\n"
)

NORMAL_PROMPT = (
    "You are a strict documentation-only support agent for TrustQueue. "
    "Your ONLY job is to answer questions using the EXACT content provided in the context below.\n\n"
    "RULES (non-negotiable):\n"
    "1. If the answer is clearly and fully supported by the context, answer it directly and cite the source.\n"
    "2. If the answer is NOT fully supported — even partially — output ONLY the token: INSUFFICIENT_CONTEXT\n"
    "3. NEVER use phrases like \"it is possible\", \"it seems\", \"it might\", \"I believe\", or any speculation.\n"
    "4. NEVER combine context clues to infer an answer that isn't explicitly stated.\n"
    "5. NEVER apologize or explain why you can't answer. Just output: INSUFFICIENT_CONTEXT\n\n"
)

SYSTEM_PROMPT = """You are TrustQueue, a documentation-aware support assistant.
You answer ONLY from the context provided below. You do not guess. You do not improvise.

RULES:
1. Answer the question directly. No preamble. No filler.
2. Never say: "Based on the context", "According to the document", "Great question", "I found", or any similar phrase.
3. If the context contains the answer: answer it in 1–3 sentences, plainly.
4. If the context does not contain a direct, explicit answer to the question asked:
   output ONLY this sentence and nothing else:
   "I don't have a reliable answer for this in our documentation. Let me connect you with the team."
   A "direct, explicit answer" means the context uses words or data that directly address what was asked.
   If you have to infer, assume, or combine unrelated facts to construct an answer: that is NOT a direct answer. Trigger handoff.
   Do NOT include a Source line in handoff responses.
5. Source attribution goes at the very end, on its own line, in this exact format:
   📄 Source: [section-title]
   Source lines apply ONLY to real answers. Never append a Source line to a handoff response.
6. Never answer from memory or general knowledge. Context is the only source of truth.

CONTEXT:
{context}
{history}"""

HANDOFF_ANSWER = (
    "I don't have enough confidence in the available documents to answer this question. "
    "Let me connect you with our team for a reliable answer."
)


async def _log_query(supabase, query: str, confidence_score: float, triggered_handoff: bool):
    logging.info(f"[CONFIDENCE] query=\"{query[:80]}\" max_similarity={confidence_score:.4f} handoff={triggered_handoff}")
    try:
        await supabase.table("query_logs").insert({
            "query": query,
            "confidence_score": confidence_score,
            "triggered_handoff": triggered_handoff,
        }).execute()
    except Exception as e:
        logging.error(f"Failed to log query: {e}")


def _needs_handoff(answer: str) -> bool:
    answer_lower = answer.lower()
    return any(phrase in answer_lower for phrase in HANDOFF_PHRASES)


class ChatMessage(BaseModel):
    role: str
    content: str


class DemoQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = None


class HandoffRequest(BaseModel):
    email: EmailStr
    question: str
    chat_context: str
    history: Optional[List[ChatMessage]] = None


class TenantQueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = None


async def _execute_tenant_query(
    tenant_id: str,
    query_text_raw: str,
    top_k: int,
    session_id: Optional[str],
    history_msgs: Optional[List[ChatMessage]],
) -> Response:
    session_id = session_id or str(uuid.uuid4())
    history = [msg.model_dump() for msg in history_msgs] if history_msgs else []
    recent_history = history[-10:]

    query_text = query_text_raw.encode('utf-8', errors='ignore').decode('utf-8')

    query_embedding = await generate_embedding(query_text)

    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    response = await supabase.rpc(
        "match_documents",
        {
            "query_embedding": query_embedding,
            "match_threshold": 0.0,
            "match_count": top_k,
            "filter_tenant_id": tenant_id,
        }
    ).execute()

    results = []
    context_texts = []
    similarities = []
    if response.data:
        for row in response.data:
            content = row.get("content", "")
            similarity = row.get("similarity", 0.0)
            context_texts.append(content)
            similarities.append(similarity)
            results.append(
                {
                    "title": row.get("title", "Unknown"),
                    "content": content,
                    "similarity": similarity,
                    "metadata": row.get("metadata", {})
                }
            )

    max_similarity = max(similarities) if similarities else 0.0

    updated_history = recent_history + [{"role": "user", "content": query_text}]

    if max_similarity < CONFIDENCE_LOW:
        await _log_query(supabase, query_text, max_similarity, True)
        updated_history.append({"role": "assistant", "content": HANDOFF_ANSWER})
        data = {
            "query": query_text,
            "answer": HANDOFF_ANSWER,
            "sources": results,
            "confidence_score": max_similarity,
            "needs_handoff": True,
            "handoff_message": (
                "I couldn't find this in our docs. "
                "Can I get your email so our team can help you directly?"
            ),
            "session_id": session_id,
            "history": updated_history,
        }
        return Response(
            content=json.dumps(data, ensure_ascii=False),
            media_type="application/json; charset=utf-8"
        )

    context = "\n\n".join(context_texts)

    history_str = ""
    if recent_history:
        history_str = "CONVERSATION HISTORY:\n"
        for msg in recent_history:
            history_str += f"{msg['role'].upper()}: {msg['content']}\n"
        history_str += "\n"

    prompt = SYSTEM_PROMPT.format(context=context, history=history_str) + "\nQuestion: " + query_text

    groq_client = GroqClient(api_key=settings.GROQ_API_KEY)
    completion = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = completion.choices[0].message.content
    answer = str(response_text).encode('utf-8', errors='ignore').decode('utf-8')

    if "INSUFFICIENT_CONTEXT" in answer:
        await _log_query(supabase, query_text, max_similarity, True)
        updated_history.append({"role": "assistant", "content": "I couldn't find a reliable answer in our documentation."})
        data = {
            "query": query_text,
            "answer": "I couldn't find a reliable answer in our documentation.",
            "sources": results,
            "confidence_score": 0.0,
            "needs_handoff": True,
            "session_id": session_id,
            "history": updated_history,
        }
        data["handoff_message"] = (
            "I couldn't find this in our docs. "
            "Can I get your email so our team can help you directly?"
        )
        return Response(
            content=json.dumps(data, ensure_ascii=False),
            media_type="application/json; charset=utf-8"
        )

    handoff = _needs_handoff(answer)
    if handoff:
        answer = re.sub(r"\n*\s*📄\s*Source:.*$", "", answer, flags=re.MULTILINE).rstrip()
    await _log_query(supabase, query_text, max_similarity, handoff)

    updated_history.append({"role": "assistant", "content": answer})

    data = {
        "query": query_text,
        "answer": answer,
        "sources": results,
        "confidence_score": max_similarity,
        "needs_handoff": handoff,
        "session_id": session_id,
        "history": updated_history,
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

@router.post("/query")
async def query_documents(request: QueryRequest, user=Depends(get_current_user)):
    try:
        # Decode user query with utf-8
        query_text = request.query.encode('utf-8', errors='ignore').decode('utf-8')

        # 1. Generate embedding for the query
        query_embedding = await generate_embedding(query_text)

        # 2. Connect to Supabase
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        
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

        # 4. Format the response and calculate confidence
        results = []
        context_texts = []
        similarities = []
        if response.data:
            for row in response.data:
                content = row.get("content", "")
                similarity = row.get("similarity", 0.0)
                context_texts.append(content)
                similarities.append(similarity)
                results.append(
                    {
                        "title": row.get("title", "Unknown"),
                        "content": content,
                        "similarity": similarity,
                        "metadata": row.get("metadata", {})
                    }
                )

        max_similarity = max(similarities) if similarities else 0.0

        # 5. Confidence-based routing
        if max_similarity < CONFIDENCE_LOW:
            await _log_query(supabase, query_text, max_similarity, True)
            data = {
                "query": query_text,
                "answer": HANDOFF_ANSWER,
                "results": results,
                "confidence_score": max_similarity,
                "needs_handoff": True,
                "handoff_message": (
                    "I couldn't find this in our docs. "
                    "Can I get your email so our team can help you directly?"
                ),
            }
            return Response(
                content=json.dumps(data, ensure_ascii=False),
                media_type="application/json; charset=utf-8"
            )

        context = "\n\n".join(context_texts)
        if max_similarity < CONFIDENCE_HIGH:
            prompt = CONSERVATIVE_PROMPT + "Context:\n" + context + "\n\nQuestion: " + query_text
        else:
            prompt = NORMAL_PROMPT + "Context:\n" + context + "\n\nQuestion: " + query_text

        groq_client = GroqClient(api_key=settings.GROQ_API_KEY)
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = completion.choices[0].message.content
        answer = str(response_text).encode('utf-8', errors='ignore').decode('utf-8')
        source_name = results[0]["title"] if results else "Unknown"
        answer += f"\n\n📄 Source: [{source_name}]"

        await _log_query(supabase, query_text, max_similarity, False)

        data = {
            "query": query_text,
            "answer": answer,
            "results": results,
            "confidence_score": max_similarity,
            "needs_handoff": False,
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
async def demo_query(request: DemoQueryRequest, req: Request):
    client_ip = req.client.host if req.client else "unknown"
    _check_demo_rate_limit(client_ip)

    try:
        return await _execute_tenant_query(
            tenant_id=DEMO_TENANT_ID,
            query_text_raw=request.query,
            top_k=request.top_k,
            session_id=request.session_id,
            history_msgs=request.history,
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


@router.post("/query/{tenant_id}")
async def tenant_query(tenant_id: str, request: TenantQueryRequest):
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id: must be a UUID")

    try:
        return await _execute_tenant_query(
            tenant_id=tenant_id,
            query_text_raw=request.query,
            top_k=5,
            session_id=request.session_id,
            history_msgs=request.history,
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
        history_text = ""
        if request.history:
            history_text = "\n".join(
                f"{msg.role.upper()}: {msg.content}" for msg in request.history
            )

        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        support_email = "stergios.z@trustqueue.com"
        slack_webhook_url: str | None = None
        try:
            settings_resp = (
                await supabase.table("settings")
                .select("support_email, slack_webhook_url")
                .eq("tenant_id", DEMO_TENANT_ID)
                .maybe_single()
                .execute()
            )
            if settings_resp and settings_resp.data:
                support_email = settings_resp.data.get("support_email") or support_email
                slack_webhook_url = settings_resp.data.get("slack_webhook_url")
        except Exception:
            logging.warning("Tenant settings lookup failed; using defaults", exc_info=True)

        await supabase.table("handoff_requests").insert({
            "email": request.email,
            "question": request.question,
            "chat_context": request.chat_context,
            "history": history_text or None,
            "status": "pending",
        }).execute()

        if settings.RESEND_API_KEY:
            email_body = (
                f"Customer email: {request.email}\n"
                f"Question: {request.question}\n"
                f"Chat context: {request.chat_context}"
            )
            if history_text:
                email_body += f"\n\nFull conversation history:\n{history_text}"

            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": "stergios.z@trustqueue.com",
                        "to": [support_email],
                        "subject": "TrustQueue - Human needed",
                        "text": email_body,
                    },
                )

        # Fire-and-forget Slack notification — never blocks the response
        asyncio.create_task(
            notify_handoff(
                email=request.email,
                question=request.question,
                chat_context=history_text or request.chat_context,
                session_id=getattr(request, "session_id", None),
                webhook_url=slack_webhook_url,
            )
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


@router.get("/public/stats")
async def public_stats():
    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        logs_resp = await supabase.table("query_logs").select("confidence_score, triggered_handoff").execute()
        rows = logs_resp.data or []

        total_queries = len(rows)
        answered = sum(1 for r in rows if not r["triggered_handoff"])
        avg_confidence = (
            sum(r["confidence_score"] for r in rows) / total_queries
            if total_queries > 0 else 0.0
        )
        resolution_rate = (answered / total_queries * 100) if total_queries > 0 else 0.0

        handoffs_resp = await supabase.table("handoff_requests").select("status").execute()
        total_handoffs = len(handoffs_resp.data or [])

        return {
            "total_queries": total_queries,
            "resolution_rate": round(resolution_rate, 2),
            "avg_confidence": round(avg_confidence, 4),
            "total_handoffs": total_handoffs,
        }
    except Exception:
        return {
            "total_queries": 0,
            "resolution_rate": 0,
            "avg_confidence": 0,
            "total_handoffs": 0,
        }


@router.get("/admin/stats")
async def admin_stats(req: Request):
    admin_key = req.headers.get("X-Admin-Key")
    if admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")

    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        logs_resp = await supabase.table("query_logs").select("confidence_score, triggered_handoff").execute()
        rows = logs_resp.data or []

        total_queries = len(rows)
        answered = sum(1 for r in rows if not r["triggered_handoff"])
        handed_off = sum(1 for r in rows if r["triggered_handoff"])
        avg_confidence = (
            sum(r["confidence_score"] for r in rows) / total_queries
            if total_queries > 0 else 0.0
        )
        resolution_rate = (answered / total_queries * 100) if total_queries > 0 else 0.0

        handoffs_resp = await supabase.table("handoff_requests").select("status").execute()
        handoff_rows = handoffs_resp.data or []

        total_handoffs = len(handoff_rows)
        pending_handoffs = sum(1 for r in handoff_rows if r["status"] == "pending")

        return {
            "query_stats": {
                "total_queries": total_queries,
                "answered": answered,
                "handed_off": handed_off,
                "avg_confidence": round(avg_confidence, 4),
                "resolution_rate": round(resolution_rate, 2),
            },
            "handoff_stats": {
                "total_handoffs": total_handoffs,
                "pending_handoffs": pending_handoffs,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        full_trace = traceback.format_exc()
        logging.error(f"FULL ERROR: {full_trace}")
        return JSONResponse(
            content={"error": "An internal server error occurred.", "details": str(e)},
            status_code=500
        )
