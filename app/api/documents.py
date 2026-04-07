from fastapi import APIRouter, HTTPException
from supabase import create_async_client
from app.core.config import settings

router = APIRouter()

@router.get("/documents")
async def get_documents():
    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        # We fetch records and group them in Python. For a production system with millions
        # of rows, it is highly recommended to use an RPC or View in Supabase to perform
        # the grouping natively in PostgreSQL:
        # SELECT title, COUNT(*) as chunks, MIN(created_at) as uploaded_at FROM documents GROUP BY title ORDER BY uploaded_at DESC;
        
        response = await supabase.table("documents").select("title, created_at").execute()
        
        doc_map = {}
        if response.data:
            for row in response.data:
                title = row.get("title", "Unknown")
                created_at = row.get("created_at") or "1970-01-01T00:00:00+00:00"
                
                if title not in doc_map:
                    doc_map[title] = {"title": title, "chunks": 0, "uploaded_at": created_at}
                
                doc_map[title]["chunks"] += 1
                if created_at < doc_map[title]["uploaded_at"]:
                    doc_map[title]["uploaded_at"] = created_at
                    
        docs = list(doc_map.values())
        docs.sort(key=lambda x: x["uploaded_at"], reverse=True)
        
        return {"documents": docs}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents/{title}")
async def delete_document(title: str):
    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        # Delete all chunks for this title
        response = await supabase.table("documents").delete().eq("title", title).execute()
        
        # PostgREST delete returns the deleted rows if header Prefer: return=representation is set, 
        # but the supabase-py client handles returning the data if configured. 
        # We'll just return a success message.
        return {"message": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
