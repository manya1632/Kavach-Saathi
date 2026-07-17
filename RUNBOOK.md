# RUNBOOK — Judge/Reviewer Walkthrough

This is the exact, step-by-step path to see every agent do real work — real model
calls, real database writes, real external APIs — not fixture reads. For local setup
mechanics (Docker, keys, troubleshooting), see [SETUP.md](SETUP.md) first; this file
assumes the stack is already running.

```bash
docker compose up -d
curl http://localhost:8000/health   # {"status":"ok", ...real product/order/return counts}
```

Storefront: <http://localhost:3000> · Seller portal: <http://localhost:3000/seller> ·
Admin console: <http://localhost:3000/admin> · API docs: <http://localhost:8000/docs>

## How to confirm any given run was real, not fixture

Every agent call writes a row to the `agent_logs` table with a genuine `confidence`,
`latency_ms`, and `provider` string. After triggering any agent below:

```sql
SELECT agent_name, confidence, latency_ms, provider, created_at
FROM agent_logs ORDER BY id DESC LIMIT 5;
```

or

```bash
docker compose exec postgres psql -U kavach -d kavach_saathi \
  -c "SELECT agent_name, confidence, latency_ms, provider FROM agent_logs ORDER BY id DESC LIMIT 5;"
```

A `latency_ms` in the hundreds-to-tens-of-thousands range and a real provider name
(`gemini`, `groq`, `clip+resnet50+gemini`, `nano_banana_2`, etc.) is what a genuinely
computed result looks like; a demo/fixture path would show `provider="demo_deterministic"`
with near-zero latency.

## Golden demo IDs

- Buyer: `B-001` (Sunita, Hindi preference) · Seller: `S-001` · Product: `P-001`
  (Maroon Floral Cotton Kurta) · Order: `O-GOLDEN`
- Admin: `admin@kavachsaathi.test` / `KavachDemo@2026` (seeded by
  `scripts/generate_seed_data.py`; this is the **only** account that can reach
  `/admin` — there is no public admin signup)

## Buyer journey (all real)

1. **Sign up** at the storefront — real bcrypt + JWT, not a hardcoded `B-001`.
2. **Browse** — 500+ seeded products across 10 categories.
3. **Ask a product question** (voice icon) — text or real microphone recording.
   Triggers Agent 3 (Pinecone size RAG) then Agent 5 (Sarvam ASR/TTS + Pinecone RAG
   grounding + Gemini/Groq). With `SARVAM_API_KEY` configured, the reply is audible,
   real synthesized Hindi/English audio.
4. **Add to cart, checkout** — real `cart_items`/`orders` rows, COD or Razorpay
   sandbox. Placing a COD order publishes `order.placed` on Redis Streams, which
   **automatically** places a real Twilio phone call (Agent 7) — see the dedicated
   section below before doing this if you don't want a real call yet.
5. **Post a review with a photo** — publishes `review.submitted`, which automatically
   triggers Agent 4 (CLIP + BERT) in the background within a few seconds. Check
   `agent_logs` or refresh the product page to see whether the photo was hidden.
6. **Verify an address** — checkout's address step calls Agent 6 (real Google Maps
   Geocoding + IndicNLP normalization + DIGIPIN).

## Seller journey (all real)

1. **Sign up as a seller** at `/seller`.
2. **Add Product → pick "Who is this product for?"** (a garment audience, or "Not a
   garment" for bags/footwear/jewellery/etc.), then upload 2-4 product photos and 1-2
   catalogue/label/tag photos, and click **Initialize listing & extract specs**. This
   triggers Agent 1 (SAM 2.1 segmentation → the FASHN/Nano-Banana/Stable-Diffusion
   provider cascade, 4 catalogue views — skipped for non-garment products, which reuse
   the seller's own photos as-is) and Agent 2 (OCR on every uploaded photo + CLIP/
   ResNet-50 as a fallback for whatever the label didn't print) as a background run —
   **this is genuinely slow** (real CPU/API inference, low minutes) and that is
   expected, not a bug. Poll status in the UI or via `GET /v1/runs/{run_id}`.
3. **Finalize Product Details:** the spec block (4 fields for garments — fabric, gsm,
   colour, wash care; 2 for non-garment — material, colour) is read-only, autofilled
   from what Agent 2 actually extracted — nothing here is seller-editable by design (a
   printed label is trusted directly; the seller can't override it). Add a size chart
   (required for garments, optional otherwise) and **Publish Listing**.
4. **Check the Inventory tab** — a listing whose images haven't passed AI verification
   yet shows **Delete**/**Try again**; once verified it shows a read-only card (photo +
   specs, no editable variant form).
5. **Check the Orders tab** — a read-only status view (delivered/cancelled/returned/
   etc.) of orders placed against this seller's listings; order-status transitions
   themselves are still validated against the real state machine
   (`order_status.py`, `409` on an out-of-sequence transition) but are driven by the
   buyer/delivery flow, not a seller-side "mark packed/shipped" action.

## Admin console

1. Log in at `/admin` with the seeded admin account above.
2. **Dashboard** — real platform counts and real per-agent average confidence pulled
   from `agent_logs`.
3. **Inspection Queue** — real `returns` rows Agent 8 sent to manual review (see the
   Return Verifier edge case below to populate one). Approve or reject; this writes
   the order's real `return_outcome` and immediately recomputes that seller's and
   buyer's trust score.
4. **Fraud Cases** — real stolen-photo-flagged products (Agent 1) and sellers/buyers
   with `fraud_flags > 0`.
5. **Trust Override** — manually set a seller's `trust_score`/`verified`, or trigger
   **Recompute all trust scores**, which re-runs the same real computation
   (`trust_jobs.py`) against every seller/buyer's actual order/return/agent_logs data.

## Return Verifier (Agent 8) — all three real outcome paths

Real video files with genuinely different content are seeded at
`assets/mock/returns/return-{approve,request_more_evidence,manual_inspection}.mp4`.
Each of these drives its named outcome through real, unmocked CLIP + ResNet-50
similarity scoring and OCR — nothing about the outcome is hardcoded to the filename:

```bash
curl -sS http://localhost:8000/v1/returns/analyze \
  -H 'content-type: application/json' \
  -d '{"order_id":"O-GOLDEN","video_key":"assets/mock/returns/return-approve.mp4"}'
# poll GET /v1/runs/{run_id} until status leaves queued/running
```

Swap `video_key` to `return-request_more_evidence.mp4` or `return-manual_inspection.mp4`
against the same order to see the other two thresholds — a `manual_inspection` result
appears in the admin console's Inspection Queue immediately.

## Forcing the Agent 1 image-generation fallback

Agent 1 tries providers in order: FASHN's paid API → Nano Banana 2 (Gemini) → the free
FASHN Hugging Face Space → Hugging Face FLUX.1 Kontext → self-hosted Stable Diffusion +
ControlNet. To see the real Stable Diffusion + ControlNet fallback without burning real
API calls first, unset/comment out `FASHN_API_KEY`, `GEMINI_API_KEY`, and
`HUGGINGFACE_API_KEY` in `.env` (leaving all of them configured just exercises FASHN,
never reaching the fallback) — or, to specifically force past just Nano Banana while
keeping the other providers live, lower its quota:

```bash
# in .env
NANO_BANANA_DAILY_QUOTA=0
docker compose restart backend
```

The next listing analysis will show `provider: "stable_diffusion_controlnet"` on every
generated view instead of `"nano_banana_2"`. Revert the value and restart to go back to
the real Gemini path.

## Agent 7's real phone call

This one **places an actual phone call to a real number** — only do this
intentionally.

1. Start a public tunnel to your local backend (Twilio cannot reach `localhost`):
   ```bash
   ngrok http 8000
   ```
2. Set `PUBLIC_BASE_URL` in `.env` to the `https://...ngrok-free.dev` URL ngrok prints,
   and set `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER`. Restart
   the backend.
3. Set a real, Twilio-verified phone number on a test buyer's account (trial Twilio
   accounts can only call verified numbers), then place a COD order for that buyer —
   `order.placed` triggers the real call automatically.
4. Answer and say "yes", "no", or ask to reschedule — Sarvam ASR transcribes your
   reply and the reasoning provider classifies the intent for real.
5. **Unreachable-call edge case:** don't answer, or hang up immediately. After
   `AGENT7_MAX_RETRIES` unanswered attempts the order's confirmation record shows a
   real WhatsApp fallback message was sent instead (Twilio sandbox number) — check
   `agent_logs` for `agent_name="delivery_confirmation"` with the fallback noted in
   `output_json`.

Without `PUBLIC_BASE_URL`/Twilio credentials configured, `initiate_call` honestly
reports "not configured" — the automatic trigger on `order.placed` no-ops rather than
pretending a call happened.

## Verifying honest degradation (pull a key, watch it fail honestly)

Pick any provider key in `.env`, blank it, restart the backend, and re-trigger the
matching agent — every one of these has a documented, non-fabricated fallback (see
`docs/AGENTS.md`):

| Key removed | Agent | Observable honest-degrade behavior |
|---|---|---|
| `GEMINI_API_KEY` and `GROQ_API_KEY` | 1, 2, 3, 5, 7, 8 | Falls to `DemoReasoningProvider`, which raises `ReasoningUnavailable`; each agent's deterministic fallback path runs instead, and the response says so. |
| `GOOGLE_MAPS_API_KEY` | 6 | Response status becomes `needs_evidence` with a `geocode_error` in the evidence — the postal PIN is never claimed to match without a real check. |
| `SARVAM_API_KEY` | 5, 7 | Agent 5 falls back to template text answers (no audio fabricated); Agent 7's call still places but uses Twilio's own `<Say>` instead of Sarvam's voice. |
| `TWILIO_ACCOUNT_SID` | 7 | `initiate_call` returns "not configured"; no call is placed, none is claimed to have been. |
| `GOOGLE_VISION_API_KEY` | 1 | Stolen-photo check reports `reverse_search_error` and never flags a product (only false negatives are possible when unconfigured, never a false accusation). |
| `DIGILOCKER_CLIENT_ID`/`SECRET` | seller KYC | `POST /seller/kyc/start` returns `{configured: false}` instead of auto-passing KYC. |
| `RAZORPAY_KEY_ID`/`SECRET` | checkout | `POST /v1/orders` with `payment_mode=prepaid` fails with `503` before writing anything, rather than silently downgrading to a fake success. |

## Automated tests

```bash
python -m pytest      # unit + integration, mocks heavy CV/model calls for CI speed
ruff check .           # backend lint
npm --prefix web run lint
npm --prefix web run build

# Playwright E2E -- real browser against a real backend/DB (docker compose up first)
cd web && npx playwright install --with-deps chromium && npm run e2e
```

Tests that specifically call out "real, unmocked pipeline verified separately, see
RUNBOOK.md" (Agent 1 image generation, Agent 2 spec extraction, Agent 4 review
relevance, Agent 8 return verification) are exercised for real by the buyer/seller
journey steps and the Return Verifier section above — pytest mocks those specific
heavy calls so the suite runs in CI time, not because the real path doesn't exist.
`web/e2e/README.md` documents exactly what the Playwright suite covers versus what's
still manual-only (Agent 1/2's full completion, Agent 7's real call, Agent 8's video
upload) and why.
