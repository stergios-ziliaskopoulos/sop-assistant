# Stale rows older than 48h can be purged by a future scheduled job:
# DELETE FROM rate_limits WHERE window_start < NOW() - INTERVAL '48 hours';

from datetime import datetime, timezone
from fastapi import HTTPException
from supabase import create_async_client
from app.core.config import settings
import logging

_limits_cache: dict[str, dict] = {}
_CACHE_TTL = 300  # seconds

_DEFAULT_PER_MINUTE = 30
_DEFAULT_PER_DAY = 2000


async def _get_rate_limits(tenant_id: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    entry = _limits_cache.get(tenant_id)
    if entry and (now - entry["at"]).total_seconds() < _CACHE_TTL:
        return entry["per_minute"], entry["per_day"]
    supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    resp = await (
        supabase.table("settings")
        .select("rate_limit_per_minute, rate_limit_per_day")
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    per_minute = _DEFAULT_PER_MINUTE
    per_day = _DEFAULT_PER_DAY
    if resp and resp.data:
        per_minute = resp.data.get("rate_limit_per_minute") or _DEFAULT_PER_MINUTE
        per_day = resp.data.get("rate_limit_per_day") or _DEFAULT_PER_DAY
    _limits_cache[tenant_id] = {"per_minute": per_minute, "per_day": per_day, "at": now}
    return per_minute, per_day


async def check_rate_limit(tenant_id: str) -> None:
    now = datetime.now(timezone.utc)
    window_start = now.replace(second=0, microsecond=0)
    window_start_iso = window_start.isoformat()

    try:
        per_minute, per_day = await _get_rate_limits(tenant_id)
    except Exception as e:
        logging.warning(f"[rate_limiter] failed to fetch limits for {tenant_id}: {e}")
        return  # Fail open

    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        # Increment per-minute counter: select → insert or update
        existing = await (
            supabase.table("rate_limits")
            .select("query_count")
            .eq("tenant_id", tenant_id)
            .eq("window_start", window_start_iso)
            .maybe_single()
            .execute()
        )

        if existing and existing.data:
            minute_count = existing.data["query_count"] + 1
            await (
                supabase.table("rate_limits")
                .update({"query_count": minute_count})
                .eq("tenant_id", tenant_id)
                .eq("window_start", window_start_iso)
                .execute()
            )
        else:
            minute_count = 1
            try:
                await (
                    supabase.table("rate_limits")
                    .insert({
                        "tenant_id": tenant_id,
                        "window_start": window_start_iso,
                        "query_count": 1,
                    })
                    .execute()
                )
            except Exception:
                # Race condition: another request inserted first — re-fetch and update
                refetch = await (
                    supabase.table("rate_limits")
                    .select("query_count")
                    .eq("tenant_id", tenant_id)
                    .eq("window_start", window_start_iso)
                    .maybe_single()
                    .execute()
                )
                if refetch and refetch.data:
                    minute_count = refetch.data["query_count"] + 1
                    await (
                        supabase.table("rate_limits")
                        .update({"query_count": minute_count})
                        .eq("tenant_id", tenant_id)
                        .eq("window_start", window_start_iso)
                        .execute()
                    )

        if minute_count > per_minute:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again in 60 seconds.",
                headers={"Retry-After": "60"},
            )

        # Per-day check: sum all per-minute windows since start of today UTC
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_resp = await (
            supabase.table("rate_limits")
            .select("query_count")
            .eq("tenant_id", tenant_id)
            .gte("window_start", today_start.isoformat())
            .execute()
        )
        daily_count = sum(r["query_count"] for r in (daily_resp.data or []))
        if daily_count > per_day:
            raise HTTPException(
                status_code=429,
                detail="Daily query limit reached for this tenant.",
                headers={"Retry-After": "3600"},
            )

    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"[rate_limiter] check failed for {tenant_id}: {e}")
        # Fail open — don't block legitimate traffic on transient DB errors
