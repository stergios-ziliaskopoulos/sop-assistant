# Progress — 2026-04-09

## What was built

### Supabase Auth integration
- **`app/core/auth.py`** — `get_current_user()` FastAPI dependency that validates JWT Bearer tokens via Supabase Auth
- **`app/api/auth.py`** — Auth endpoints:
  - `POST /api/v1/auth/register` — user registration
  - `POST /api/v1/auth/login` — user login, returns JWT access token
  - `GET /api/v1/auth/me` — returns authenticated user info
- **`app/main.py`** — updated to include the auth router

### Tenant isolation
- **`app/api/upload.py`** — requires auth, sets `tenant_id = user.id` on every inserted document
- **`app/api/query.py`** — requires auth, passes `filter_tenant_id` to `match_documents` RPC
- **`app/api/documents.py`** — requires auth, filters list and delete queries by `tenant_id`

### Dependency
- Added `email-validator` to `requirements.txt`

## What needs to be done next

### Supabase database changes
1. Add a `tenant_id` column (text or uuid) to the `documents` table
2. Update the `match_documents` RPC function to accept a `filter_tenant_id` parameter and filter with `WHERE tenant_id = filter_tenant_id`
3. Consider adding Row Level Security (RLS) policies on `tenant_id` as defense-in-depth

### Testing
1. Update existing tests (`test_health.py`, `test_ingest.py`, `test_query.py`) to account for auth requirements
2. Add tests for the new auth endpoints (register, login, me)
3. Add tests for tenant isolation (ensure users cannot access other tenants' documents)

### Frontend
1. Update `app/static/index.html` to add login/register UI
2. Store JWT token in the browser and send it as `Authorization: Bearer <token>` on all API calls

### Other considerations
- Protect `app/api/ingest.py` with auth + tenant_id (same pattern as upload)
- Add token refresh logic (Supabase tokens expire)
- Add logout endpoint if needed

## Layer 5 — Distribution

> Important: Layer 5 starts in parallel with Layer 3 — not after Layer 4.

### Directories (free traffic)
- There's An AI For That (theresanaiforthat.com)
- Futurepedia
- Toolify
- G2 listing (needs reviews from first customers)

### Community (organic, no spam)
- Reddit r/SaaS — post: "I built an AI support agent with flat pricing, no Intercom bill shock"
- IndieHackers — build in public posts
- LinkedIn — founder story posts

### Product Hunt launch
- Only after working product with live demo exists
- Prepare demo video (1 min Loom)
- Target: Tuesday or Wednesday launch
