# Kavach Saathi

Kavach Saathi is an agentic commerce-safety prototype for trustworthy marketplace
shopping. Its Next.js storefront and FastAPI backend use eight coordinated AI agents
to check product claims, sizing, reviews, addresses, delivery confirmation, and
returns using real evidence — not fixture data pretending to be AI. The included demo
data is synthetic.

## Why it matters

Online buyers often face misleading listings, inconsistent sizes, irrelevant review
media, address failures, unwanted deliveries, and return disputes. Kavach Saathi adds
explainable checks and human-safe fallbacks at the points where these failures occur.
Confidence scores are evidence signals, never proof of fraud, and a missing API key
degrades honestly to "not configured" rather than faking a result.

## Features

- Four role-scoped web apps sharing one backend: buyer storefront, seller portal,
  delivery portal, and admin console.
- Real cart, checkout (COD and Razorpay sandbox prepaid), wishlist, addresses, orders,
  reviews, and returns.
- Image-first seller listing flow: upload product + label photos, and Agent 1/Agent 2
  do the catalogue-image generation and spec extraction — nothing is seller-typed and
  trusted blindly.
- WhatsApp-based order confirmation, delivery scheduling, and return/exchange flows
  (Twilio), plus a Vishwas Saathi in-app chat assistant.
- Evidence-backed AI results with bilingual (and beyond) buyer messages and optional
  voice support.
- Deterministic demo mode: the whole stack runs and is fully explorable with zero API
  keys configured — every agent just honestly reports what it couldn't check.

## System architecture

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Buyer web   │     │ Seller portal│     │Delivery portal│     │Admin console │
│ (storefront) │     │  (/seller)   │     │  (/delivery)  │     │   (/admin)   │
└──────┬───────┘     └──────┬───────┘     └──────┬────────┘     └──────┬───────┘
       │                    │                     │                     │
       └────────────────────┴────────┬────────────┴─────────────────────┘
                                      │  Next.js :3000 (single app, role-scoped routes)
                                      │  /agent-api/* rewrite proxy
                                      ▼
                          ┌───────────────────────┐
                          │     FastAPI :8000      │
                          │  auth · commerce ·      │
                          │  seller · delivery ·    │
                          │  admin · specs routers  │
                          └───────────┬─────────────┘
                                      │
                 ┌────────────────────┼─────────────────────┐
                 ▼                    ▼                      ▼
      ┌────────────────────┐ ┌────────────────┐   ┌───────────────────────┐
      │ OrchestrationService │ │  Postgres 16   │   │        Redis 7        │
      │  + LangGraph workflows│ │  26 tables     │   │ cache + Streams event │
      │  (Agents 1-8)         │ │                │   │ bus (order.placed,    │
      └──────────┬─────────┘ └────────────────┘   │ review.submitted)      │
                 │                                  └───────────────────────┘
                 ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ Self-hosted models: SAM 2.1 · CLIP · ResNet-50 · Stable Diffusion │
    │ Real external APIs (each independently config-gated):             │
    │ Gemini · Groq · FASHN · Hugging Face · Pinecone · Sarvam ·         │
    │ Twilio (voice + WhatsApp) · Google Maps · Google Vision · Razorpay │
    └─────────────────────────────────────────────────────────────────┘
```

**Roles.** One `users` table, three roles gated by JWT (`buyer`, `seller`, `admin`) plus
a fourth (`delivery_boy`) added for the delivery portal — `require_role(...)` guards
each role's routes. There's no public admin signup; only a seeded account can reach
`/admin`.

**Agents.** LangGraph compiles one workflow graph per operation (listing analysis,
review analysis, return analysis, size/voice/address queries). Agents that call real,
slow model inference or external APIs (1, 2, 4, 8) run on a background thread so the
request returns `status: "queued"` immediately; the frontend polls
`GET /v1/runs/{run_id}` until it finishes. Every agent call writes a row to
`agent_logs` with a real confidence, latency, and provider string — the audit trail
that proves a run was genuinely computed, not read from a fixture.

| # | Agent | Role |
|---|---|---|
| 1 | Catalogue Truth Guardian | Segments the product photo (SAM 2.1) and generates real catalogue views through a 5-tier provider cascade; flags stolen/copied photos. |
| 2 | Honest Spec Enforcer | OCRs the label/tag photo for fabric, GSM, colour, wash care; CV (CLIP + ResNet-50) fills in only what the label didn't print, never overrides what it did. |
| 3 | Cross-Seller Size Translator | Recommends a size from the buyer's own measurements and cross-seller purchase history (Pinecone RAG). |
| 4 | Image-Truth Review Filter | Flags review photos that don't actually match the product. |
| 5 | Trusted Voice Q&A | Answers product questions grounded in verified specs/reviews, with optional Hindi voice. |
| 6 | Address Guardian | Validates postal/coordinate/locality/DIGIPIN consistency before delivery. |
| 7 | Delivery Confirmation | Real outbound call/WhatsApp confirming delivery details before dispatch. |
| 8 | Return Authenticity Verifier | Compares the buyer's return photo against the delivered-item photo; escalates uncertainty to manual review instead of guessing. |

See [docs/architecture.md](docs/architecture.md) for the full runtime/data-layer
writeup and [docs/AGENTS.md](docs/AGENTS.md) for a per-agent breakdown of exactly which
real model/API each one calls and how it degrades when unconfigured. For a single,
narrative walkthrough of how all of this fits together, see [EXPLAIN.md](EXPLAIN.md).

## Repository structure

```text
web/                    Next.js UI (storefront/seller/delivery/admin) and Playwright tests
src/kavach_saathi/      FastAPI app, agents, providers, orchestration, and database
migrations/             Alembic database migrations
tests/                  Python integration and feature tests
data/seed/               Synthetic demo records
assets/mock/             Synthetic demo media
scripts/                 Seed and local-development utilities
docker-compose.yml       Local PostgreSQL, Redis, backend, and frontend stack
```

## Run locally

Requirements: Docker Desktop, or Python 3.11+, [uv](https://docs.astral.sh/uv/),
Node.js 20+, PostgreSQL, and Redis. See [SETUP.md](SETUP.md) for the full walkthrough
and [RUNBOOK.md](RUNBOOK.md) for a judge/reviewer path through every agent.

The shortest path is Docker:

```bash
cp .env.example .env
docker compose up --build
```

Open the storefront at <http://localhost:3000>, the seller portal at
<http://localhost:3000/seller>, the delivery portal at
<http://localhost:3000/delivery>, the admin console at <http://localhost:3000/admin>,
and API docs at <http://localhost:8000/docs>.

For separate development processes:

```bash
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
npm --prefix web ci
uv run uvicorn kavach_saathi.app:app --reload --port 8000
npm --prefix web run dev
```

Run checks with `uv run pytest`, `uv run ruff check .`, `npm --prefix web run lint`,
and `npm --prefix web run build` — the same checks CI runs on every push (see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Attribution

Third-party packages retain their respective licenses; see
[THIRD_PARTY.md](THIRD_PARTY.md) for the full list of what's used where.
