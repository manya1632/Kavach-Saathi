# Kavach Saathi — System Architecture Explained

This is a narrative walkthrough of how Kavach Saathi is actually built and how a
request moves through it end to end. If you only read one architecture document in
this repo, read this one; [docs/architecture.md](docs/architecture.md) and
[docs/AGENTS.md](docs/AGENTS.md) go deeper on specific pieces this file summarizes.

## 1. The mental model

Kavach Saathi is a marketplace (buyer storefront + seller portal) with a trust layer
bolted onto every point where marketplaces normally let sellers/buyers/couriers get
away with an unverifiable claim: *is this listing's photo really the product, is the
fabric really what's printed on the tag, is this the right size, is this review photo
really of this product, is this delivery address real, did the buyer actually confirm
delivery, is this return item really what was delivered.* Each of those checks is one
of eight agents. An agent's job is never to accuse — it either finds real evidence and
reports a confidence score, or it honestly says it couldn't check (no key configured,
provider down, label unreadable) and falls back to the next-best signal. Nothing is
ever fabricated to look like a successful check.

## 2. The four frontend surfaces, one backend

There is a single Next.js app (`web/`) serving four role-scoped route trees, all
talking to the same FastAPI backend through one `/agent-api/*` rewrite proxy (so
provider API keys never reach the browser):

| Route | Who | What |
|---|---|---|
| `/` , `/products/*`, `/account/*`, `/support` | Buyer | Browse, cart, checkout, wishlist, addresses, orders, reviews, returns |
| `/seller`, `/seller/kyc` | Seller | Image-first listing creation, inventory, orders, DigiLocker KYC |
| `/delivery` | Delivery agent | Scheduled/pending deliveries, OTP confirmation queue |
| `/admin` | Admin (single seeded account) | Return inspection queue, fraud cases, platform analytics |

Each role's browser session is stored under its own `localStorage` key
(`kavach.auth.<role>.v1`), keyed off which route is currently loaded — so a seller and
a buyer session can coexist in different tabs of the same browser without one silently
overwriting the other's login.

## 3. The backend, module by module

`src/kavach_saathi/` is one FastAPI app (`app.py`) that mounts several routers, each
owning one slice of the domain:

- `commerce_api.py` — cart, checkout, orders, reviews, returns, wishlist, addresses (buyer-facing)
- `seller_api.py` — seller profile, KYC, image-first product listing/publish/delete, seller orders
- `delivery_api.py` — delivery-agent queue, OTP confirmation, WhatsApp-driven reschedule/cancel
- `admin_api.py` — return inspection, fraud cases, analytics (admin-only)
- `specs_api.py` — the standalone Agent 2 extract/submit-missing endpoints
- `auth.py` — signup/login/refresh, JWT issuing, bcrypt hashing, `require_role(...)` guards
- `events.py` — Redis Streams consumer threads that auto-trigger Agents 4 and 7
- `repository.py` — `CommerceRepository`, the single data-access layer everything else calls through
- `orchestration/` — the LangGraph graph + service that actually runs the 8 agents
- `agents/` — the 8 agents themselves
- `providers/` — one adapter class per external API or self-hosted model, each independently config-gated

Nothing talks to Postgres directly except `repository.py` — routers and agents call
into it, never raw SQL scattered across the codebase.

## 4. Request lifecycle: sync vs. agent workflows

Most routes are plain synchronous FastAPI handlers: auth, storefront browsing, cart,
most of seller/delivery/admin CRUD. These return immediately.

Four operations are different because they call *real* model inference or external
APIs that can take real seconds-to-minutes (self-hosted SAM2/Stable Diffusion CPU
inference, a live Gemini/Groq call, a real Twilio phone call): listing analysis
(Agents 1+2), review analysis (Agent 4), return analysis (Agent 8), and the
voice/size-query path (Agents 3+5). Their endpoints (`POST /v1/listings/analyze`,
`/v1/reviews/analyze`, `/v1/returns/analyze`, `/v1/voice/query`) return
`status: "queued"` immediately and hand the actual work to a dedicated background
thread with its own event loop — a plain `asyncio.create_task()` was deliberately
avoided because some ASGI transports tear down the request's event loop the moment the
request coroutine returns, which would silently kill an in-flight model call. The
frontend polls `GET /v1/runs/{run_id}` (or reads the `GET /v1/runs/{run_id}/events`
SSE stream) until the run reaches a terminal status, exactly the same way a judge
running `curl` against that endpoint would.

Two more triggers are fully event-driven, not polled at all: placing an order
(`POST /v1/orders`) publishes `order.placed` onto a Redis Stream, and posting a review
(`POST /v1/reviews`) publishes `review.submitted`. Two consumer-group threads started
at FastAPI startup pick these up with real `XREADGROUP`/`XACK` semantics (pending-entry
redelivery on crash, not a polling shortcut) and automatically run Agent 7 (delivery
confirmation call) and Agent 4 (review relevance check) — no manual "check this review"
button anywhere in the UI.

Every agent call, sync or async, writes one row to `agent_logs` with a genuine
`confidence`, `latency_ms`, `input_ref`, and `provider` string. That table is the audit
trail: a `latency_ms` in the hundreds-to-tens-of-thousands range and a real provider
name (`gemini`, `groq`, `clip+resnet50`, `fashn_api`, ...) is what an actually-computed
result looks like; `provider="demo_deterministic"` with near-zero latency is what an
honestly-unconfigured fallback looks like. Nothing in between is possible — there's no
code path that fabricates a plausible-looking result.

## 5. The eight agents

- **Agent 1 — Catalogue Truth Guardian** (`agents/catalogue.py`). SAM 2.1 segments the
  garment out of the seller's photo. A five-tier provider cascade generates the actual
  front/back/left/right catalogue views: FASHN's paid Try-On API → Nano Banana 2
  (Gemini image-gen, quota-tracked in Redis) → the free FASHN Hugging Face Space →
  Hugging Face FLUX.1 Kontext → self-hosted Stable Diffusion + ControlNet as the final,
  always-available fallback. Non-garment products (bags, jewellery) skip generation
  entirely — there's no "model wearing it" to render — and use the seller's own photos
  as-is. Also runs real OpenCV image-quality scoring and a real Google reverse-image
  search for stolen/copied catalogue photos.
- **Agent 2 — Honest Spec Enforcer** (`agents/specs.py`). A Groq-first (Gemini-fallback)
  multimodal model reads every uploaded photo — including a photo taken specifically of
  the care label/tag — for fabric composition, GSM, colour, and wash-care text. A
  printed label is ground truth: if OCR actually read a value, it's used directly, never
  cross-checked against a rough CV guess and blocked as a "conflict". CLIP + ResNet-50
  only ever fill in a field the label genuinely didn't print (colour, almost always,
  since labels rarely print one). GSM/wash-care have no visual signal at all, so if
  they're not on the label, they're honestly left unset rather than guessed.
- **Agent 3 — Cross-Seller Size Translator** (`agents/size.py`). Recommends a size from
  the buyer's own stored measurements against the seller's size chart, falling back to
  cross-seller purchase-history RAG (Pinecone) when there's no exact chart match, and to
  plain product popularity when there's no history either — always labelled with which
  tier actually produced the answer.
- **Agent 4 — Image-Truth Review Filter** (`agents/review.py` / `review_summary.py`).
  Runs automatically on every submitted review via the Redis Streams consumer. Real
  CLIP-based image-relevance scoring flags a review photo that doesn't actually match
  the product it's attached to.
- **Agent 5 — Trusted Voice Q&A** — grounds product-question answers in verified specs
  and reviews (Pinecone RAG), with real Sarvam AI Hindi speech-to-text/text-to-speech
  for voice input/output.
- **Agent 6 — Address Guardian** (`agents/address.py`). Real Google Maps geocoding
  cross-checked against buyer-entered postal/locality/DIGIPIN data before a delivery is
  scheduled.
- **Agent 7 — Delivery Confirmation** (`agents/confirmation.py`). Triggered
  automatically by the `order.placed` event; places a real outbound Twilio call (or
  WhatsApp message) confirming delivery details, records the buyer's real response.
- **Agent 8 — Return Authenticity Verifier** (`agents/return_verifier.py`). Compares the
  buyer's return photo against the original delivery photo using real multimodal
  comparison (`providers/return_provider.py`); low-confidence or conflicting results
  route to manual admin inspection rather than an automatic approve/deny.

## 6. Data layer

One Postgres database, 26 tables (`src/kavach_saathi/db/models.py`), covering users,
products/specs/variants/images, cart/orders/order-items/status-history, payments,
reviews, returns, addresses, agent logs, workflow-run state, buyer/seller trust
signals, OTP sessions, and the Vishwas Saathi chat history. `scripts/generate_seed_data.py`
seeds deterministic demo data (500 products across 10 categories, buyers, sellers, one
`ADMIN-001` account, orders, reviews, returns) directly into Postgres — the exact same
script CI runs against a fresh database on every push.

Redis serves two roles: a cache (session/quota tracking), and the Streams-based event
bus described above.

## 7. Auth and roles

JWT access (short-lived) + refresh (rotating, hashed at rest) tokens, bcrypt password
hashing, one `users` table shared by all four roles (`buyer`, `seller`, `admin`,
`delivery_boy`). `require_role(...)` guards every seller/delivery/admin route. There is
no public admin signup endpoint by design — self-service admin creation would be a real
privilege-escalation hole, so the only admin account is the one seeded at startup.

## 8. Honest degradation, as a design rule

Every external provider adapter (`providers/*.py`) is independently gated on its own
API key and raises a typed `*Unavailable` exception when that key is absent — Gemini,
Groq, FASHN, Hugging Face, Pinecone, Sarvam, Twilio, Google Maps, Google Vision,
Razorpay, DigiLocker. The calling agent catches that exception and falls back to the
next real signal it has (another provider in a cascade, a cross-check with a different
model, a seller-declared value), and if it genuinely has nothing left, it reports
"not configured" rather than returning a plausible-looking fabricated result. This
rule holds everywhere in the codebase, not just where it's convenient — it's the one
architectural principle every agent, every provider, and every fallback path in this
document is actually built around.
