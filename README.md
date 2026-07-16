# Kavach Saathi

Kavach Saathi is an agentic commerce-safety prototype for trustworthy marketplace shopping. Its Next.js storefront and FastAPI backend use eight coordinated AI agents to check product claims, sizing, reviews, addresses, delivery confirmation, and returns using available evidence. The included demo data is synthetic.

## Why it matters

Online buyers often face misleading listings, inconsistent sizes, irrelevant review media, address failures, unwanted deliveries, and return disputes. Kavach Saathi adds explainable checks and human-safe fallbacks at the points where these failures occur; confidence scores are evidence signals, never proof of fraud.

## Features

- Responsive buyer storefront, seller portal, support view, cart, checkout, wishlist, addresses, orders, reviews, returns, and demo card payments.
- Deep-linkable account pages and accessible in-app dialogs.
- Evidence-backed AI results with bilingual buyer messages and optional voice support.
- FastAPI contracts, PostgreSQL/SQLAlchemy persistence, Redis events, upload handling, Razorpay live integration, and deterministic demo mode.
- Shared, process-wide model/client registry with optional warm-up.

## Agentic AI core

| Agent | Role |
|---|---|
| 1. Catalogue Truth Builder | Checks listing media and catalogue completeness. |
| 2. Honest Spec Enforcer | Compares seller claims with label and image evidence. |
| 3. Cross-Seller Size Translator | Recommends sizes from measurements and purchase history. |
| 4. Image-Truth Review Filter | Detects irrelevant or misleading review media. |
| 5. Trusted Voice Q&A | Answers product questions from grounded evidence. |
| 6. Address Guardian | Validates postal, coordinate, locality, and DIGIPIN consistency. |
| 7. Delivery Confirmation | Records pre-delivery buyer confirmation or changes. |
| 8. Return Authenticity Verifier | Compares return evidence and escalates uncertainty. |

LangGraph workflows orchestrate the agents. FastAPI validates requests and persists domain state, agents call reusable provider adapters and models, and Redis-backed events trigger background work such as review analysis and delivery confirmation.

## Architecture

```text
Browser -> Next.js storefront -> FastAPI API -> LangGraph workflows -> 8 agents
                                   |                    |
                                   v                    v
                          PostgreSQL / Redis     model & provider registry
                                   |
                            media/upload storage
```

## Repository structure

```text
web/                    Next.js UI and Playwright tests
src/kavach_saathi/      FastAPI app, agents, providers, orchestration, and database
migrations/             Alembic database migrations
tests/                  Python integration and feature tests
data/seed/              Synthetic demo records
assets/mock/             Synthetic demo media
scripts/                 Seed and local-development utilities
docker-compose.yml       Local PostgreSQL, Redis, backend, and frontend stack
```

## Run locally

Requirements: Docker Desktop, or Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20+, PostgreSQL, and Redis.

The shortest path is Docker:

```bash
cp .env.example .env
docker compose up --build
```

Open the storefront at <http://localhost:3000> and API docs at <http://localhost:8000/docs>.

For separate development processes:

```bash
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
npm --prefix web ci
uv run uvicorn kavach_saathi.app:app --reload --port 8000
npm --prefix web run dev
```

Run checks with `uv run pytest`, `uv run ruff check .`, `npm --prefix web run lint`, and `npm --prefix web run build`.

## Attribution


Third-party packages retain their respective licenses. 