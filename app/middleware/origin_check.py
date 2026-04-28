from urllib.parse import urlparse
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from supabase import create_async_client
from app.core.config import settings
import logging

_cache: dict[str, dict] = {}
_CACHE_TTL = 300  # seconds


async def _get_allowed_domains(tenant_id: str) -> list[str]:
    now = datetime.now(timezone.utc)
    entry = _cache.get(tenant_id)
    if entry and (now - entry["at"]).total_seconds() < _CACHE_TTL:
        return entry["domains"]
    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    resp = await (
        supabase.table("settings")
        .select("allowed_domains")
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    domains: list[str] = []
    if resp and resp.data:
        domains = resp.data.get("allowed_domains") or []
    _cache[tenant_id] = {"domains": domains, "at": now}
    return domains


async def check_origin(req: Request, tenant_id: str) -> None:
    origin = req.headers.get("origin")
    if not origin:
        return  # No Origin header — server-side / curl / Postman, allow

    try:
        hostname = urlparse(origin).hostname or ""
    except Exception:
        hostname = ""

    try:
        allowed = await _get_allowed_domains(tenant_id)
    except Exception as e:
        logging.warning(f"[origin_check] settings lookup failed for {tenant_id}: {e}")
        return  # Fail open on transient DB error

    if not allowed:
        return  # No restrictions configured — backwards compatible, allow

    if hostname in allowed:
        return

    raise HTTPException(status_code=403, detail="Origin not allowed for this tenant")
