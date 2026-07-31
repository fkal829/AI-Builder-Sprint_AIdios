# Repository guide

## Product

단디계약 is a mobile-first contract lifecycle management service for small tourism businesses in Busan. The P0 demo path is upload, extraction, evidence-backed review, one structured adjustment round, revised-contract verification, Modusign signing, one obligation check, and renewal timing.

## Boundaries

- `apps/frontend`: Next.js/TypeScript UI. Keep external secrets out of this app.
- `apps/api`: FastAPI orchestration, validation, state transitions, and external adapters.
- `packages/contracts`: shared JSON/OpenAPI contracts only; do not put runtime business logic here.
- `supabase/migrations`: append-only database migrations.
- `fixtures`: fictitious demo data and fixed AI evaluation cases.

## Rules

- Keep original document evidence (`source_page`, `source_text`, `confidence`) attached to extracted or reviewed terms.
- Perform dates, amounts, ratios, and status transitions in deterministic code.
- Put Upstage, Modusign, and Supabase calls behind adapters with explicit `mock` and `live` modes.
- Never log full contracts, personal contact details, API keys, or signing links.
- Do not auto-send requests, accept counteroffers, start signatures, approve evidence, or renew contracts.
- Update schemas and API documentation before changing persisted states or public responses.
- Add tests with each implementation change. P0 failures take priority over P1 work.
