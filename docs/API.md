# API Reference

All routes are served by FastAPI on `:8000`. Workflow/commerce/seller/admin routes use
the `/v1` prefix (`API_PREFIX` in config). The Next.js frontend never talks to this API
directly from the browser with real credentials in the request — it proxies through
`/agent-api/*` (see `web/next.config.mjs`) so provider keys stay server-side.

Interactive Swagger UI is always available at `GET /docs`; `docs/openapi.json` is a
committed snapshot of the same contract.

## Auth

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/auth/signup` | `role` is `buyer` or `seller` only — there is no public admin signup. Returns `{access_token, refresh_token, user}`. |
| `POST` | `/v1/auth/login` | `{identifier, password}`, identifier is email or phone. |
| `POST` | `/v1/auth/refresh` | Rotates the refresh token; the presented token is revoked and cannot be reused. |
| `GET` | `/v1/auth/me` | Bearer token required. |
| `PATCH` | `/v1/auth/language?language=hi` | Updates `preferred_language`. |

All authenticated routes below expect `Authorization: Bearer <access_token>`.

## Storefront (public, no auth)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/storefront/products` | Search/filter the seeded catalogue; `q`, `category` query params. |
| `GET` | `/v1/storefront/products/{product_id}` | Product + seller + review detail. |
| `GET` | `/v1/storefront/demo-context` | Golden buyer/order IDs for a scripted walkthrough. |

## Cart, checkout, reviews (buyer role)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/cart` | |
| `POST` | `/v1/cart` | `{product_variant_id, qty}` |
| `PATCH` | `/v1/cart/{item_id}` | `{qty}` |
| `DELETE` | `/v1/cart/{item_id}` | |
| `POST` | `/v1/orders` | `{address_id, payment_mode: "cod"\|"prepaid"}`. COD publishes `order.placed` immediately (triggers Agent 7's real call); `prepaid` waits for `/verify-payment`. Fails with `503` before writing anything if `payment_mode=prepaid` and Razorpay isn't configured — never silently downgrades to a fake success. |
| `POST` | `/v1/orders/{order_id}/verify-payment` | `{razorpay_order_id, razorpay_payment_id, razorpay_signature}`; verifies the real Razorpay signature, then publishes `order.placed`. |
| `GET` | `/v1/orders` | The buyer's own orders. |
| `POST` | `/v1/reviews` | `{product_id, rating, text, image_key?, order_id?}`. Publishes `review.submitted`, which auto-triggers Agent 4 in the background — `agent4_queued` in the response reflects whether the publish actually succeeded. |

## Agent workflow routes

Every workflow route returns a run envelope:

```json
{
  "run_id": "uuid",
  "trace_id": "uuid",
  "workflow": "return",
  "status": "queued | running | completed | needs_evidence | manual_review",
  "results": {
    "return_verifier": {
      "agent": "return_verifier",
      "status": "completed",
      "confidence": 92,
      "summary": "...",
      "evidence": [{"key": "...", "value": "...", "source": "...", "weight": 1.0}],
      "actions": [{"type": "...", "label": "...", "payload": {}}],
      "data": {},
      "user_message": {"en": "...", "hi": "..."}
    }
  },
  "error": null
}
```

Agents 1, 2, 4, and 8 call real, slow (seconds-to-minutes) model inference or external
APIs, so their routes return `status: "queued"` immediately. Poll
`GET /v1/runs/{run_id}` or consume `GET /v1/runs/{run_id}/events` as
`text/event-stream` until `status` leaves `queued`/`running`.

| Method | Path | Agent(s) | Sync or queued |
|---|---|---|---|
| `POST` | `/v1/listings/analyze` | 1 (Catalogue Truth) + 2 (Spec Enforcer) | queued |
| `POST` | `/v1/size/recommend` | 3 (Size Translator) | sync |
| `POST` | `/v1/reviews/analyze` | 4 (Review Filter) — manual re-check; the automatic path is the `review.submitted` event | queued |
| `POST` | `/v1/voice/query` | 3 then 5 (Voice Q&A) when the question is size-related | sync |
| `POST` | `/v1/address/verify` | 6 (Address Guardian) | sync |
| `POST` | `/v1/orders/{order_id}/confirm-simulated` | 7 (Delivery Confirmation) — manual simulate; the automatic path is Agent 7's real Twilio call on `order.placed` | sync |
| `POST` | `/v1/returns/analyze` | 8 (Return Verifier) | queued |
| `GET` | `/v1/runs/{run_id}` | — | poll target |
| `GET` | `/v1/runs/{run_id}/events` | — | SSE |

### Agent 7's real call path (not an HTTP route you call directly)

`POST /v1/orders` (COD) or a verified prepaid payment publishes `order.placed`, which
the background consumer routes to `DeliveryConfirmationAgent.initiate_call`. Twilio
then calls back into these webhooks — they exist for Twilio, not for frontend use:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/twilio/voice/{order_id}` | Returns TwiML asking the pre-generated confirmation question. |
| `POST` | `/v1/twilio/recorded/{order_id}` | Twilio posts the buyer's recorded answer here; triggers Gemini/Groq intent classification. |
| `POST` | `/v1/twilio/status/{order_id}` | Call status callback (answered/no-answer/busy/failed) — drives the WhatsApp fallback. |

`PUBLIC_BASE_URL` (an ngrok tunnel in local dev) must point at this backend for Twilio
to reach these routes.

## Seller portal (seller role)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/seller/profile` | Includes real `seller_trust_score` fields once `trust_jobs.py` has computed them. |
| `POST` | `/v1/seller/kyc/start?redirect_uri=...` | Returns `{configured: false}` honestly if `DIGILOCKER_CLIENT_ID`/`SECRET` are absent. |
| `POST` | `/v1/seller/kyc/complete` | `{code, redirect_uri}` — real DigiLocker OAuth2 code exchange. |
| `GET` | `/v1/seller/products` | List this seller's listings (draft and published), with images-verified status. |
| `POST` | `/v1/seller/products` | Create a draft product directly (form-first, no OCR). |
| `POST` | `/v1/seller/products/initialize` | Image-first flow: upload product + catalogue/label photos, kicks off Agent 1 (image gen) + Agent 2 (OCR spec extraction) as an async run. |
| `POST` | `/v1/seller/products/{product_id}/publish` | Finalizes and activates a listing initialized above; `{title, price, specifications, size_chart, seller_corrections, ...}`. Size chart is required unless the listing was marked non-garment at `/initialize`. |
| `DELETE` | `/v1/seller/products/{product_id}` | Discards a draft/pending listing (cascades its images/specs/variants). Cannot delete an already-`active` listing. |
| `PATCH` | `/v1/seller/products/{product_id}` | `{price?, status?}`. |
| `POST` | `/v1/seller/products/{product_id}/variants` | `{size, stock_qty, price?}`. |
| `GET` | `/v1/seller/orders` | Order items belonging to this seller only. |
| `PATCH` | `/v1/seller/orders/{order_id}/status` | `{status: "PACKED"\|"SHIPPED"}`, validated against the real order state machine (`order_status.py`). |

## Delivery, trust/Vishwas Samvad, and other newer routes

`delivery_api.py` (delivery confirmation/OTP flows behind the `/delivery` portal) and
the trust-messaging/chat additions to `commerce_api.py` aren't hand-documented here
yet — rather than let a hand-written table drift out of sync with the actual contract
again (as the seller-portal rows above just had), use the interactive Swagger UI at
`GET /docs` or `docs/openapi.json` (regenerated from the live app via
`scripts/export_openapi.py`, so it's always authoritative) for those.

## Admin console (admin role)

Only the seeded `ADMIN-001` account can authenticate as admin.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/admin/inspection-queue` | Real `returns` rows where Agent 8's decision was `manual_inspection`. |
| `POST` | `/v1/admin/returns/{return_id}/resolve` | `{decision: "approve"\|"reject", notes?}`; writes the order's `return_outcome` and immediately recomputes that seller's/buyer's trust score. |
| `GET` | `/v1/admin/fraud-cases` | Stolen-photo-flagged products, manual-inspection returns, sellers/buyers with `fraud_flags > 0`. |
| `GET` | `/v1/admin/analytics` | Platform counts + per-agent average confidence from real `agent_logs` rows. |
| `PATCH` | `/v1/admin/sellers/{seller_id}/trust-score` | `{trust_score?, verified?}` manual override. |
| `POST` | `/v1/admin/trust-scores/recompute` | Batch-recomputes every seller/buyer's trust score from real order/return/agent_logs data — the closest equivalent to a scheduled trust-score job without a standing task scheduler. |

## Uploads

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/uploads/presign` | `{kind, filename, content_type}` → `{upload_url, object_key}`. |
| `PUT` | `/v1/mock-uploads/{object_key}` | The local upload target `upload_url` points at. |
| `PUT` | body bytes → `object_key` | Then pass `object_key` into the relevant workflow request. |

## Golden demo IDs

Stable seeded IDs available for demonstrations:

- Buyer: `B-001` (Sunita, Hindi preference)
- Seller: `S-001`
- Product: `P-001` (Maroon Floral Cotton Kurta)
- Order: `O-GOLDEN`
- Matching review: `RV-GOOD`; irrelevant-media review: `RV-BAD`
- Admin: `admin@kavachsaathi.test`

## UI conventions for anyone integrating against this API

- Render actions from `actions`; do not infer buttons from `summary` text.
- Display `confidence` as evidence strength, never as "probability the buyer is lying."
- Preserve written review text when Agent 4 returns a `hide_media` action — only the
  photo is hidden, never the text.
- A low-confidence return must say "manual inspection," never "fraud" or "rejected."
- Never surface a raw provider error string to a buyer; use `trace_id` for support/debug
  screens instead.
