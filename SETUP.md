# Kavach Saathi — Teammate Setup Guide

This is a real, working prototype — not fixture data pretending to be AI. Real
Postgres, real auth, and all 8 agents call real models/APIs (SAM2/CLIP/ResNet
self-hosted, Gemini + Groq for reasoning, Pinecone for RAG, Sarvam for voice,
real Twilio phone calls, Razorpay sandbox payments). Everything runs in Docker,
so you don't need Python, Node, or any of those installed locally.

## 1. Prerequisites

- **Docker Desktop** — that's it. Download from docker.com if you don't have it,
  then make sure it's running (check the whale icon in your system tray).

## 2. Clone and configure

```bash
git clone https://github.com/Palak24Ol/Kavach-Saathi.git
cd Kavach-Saathi
cp .env.example .env
```

Now open `.env` and fill in the API keys — **ask Palak to share these with you
directly** (not over GitHub/Slack in plaintext if avoidable — WhatsApp/DM is fine
for a hackathon). Without keys, the app still runs, but each agent honestly
reports "not configured" and falls back to simpler logic instead of faking a
result — nothing crashes, you just won't see the real AI calls.

Minimum keys to get the full experience:
- `GEMINI_API_KEY` — powers most of the AI reasoning (Agents 2, 3, 5, 7)
- `GROQ_API_KEY` — automatic fallback when Gemini is rate-limited/overloaded
- `PINECONE_API_KEY` — size recommendations (Agent 3) and voice Q&A (Agent 5)
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — prepaid checkout
- `GOOGLE_MAPS_API_KEY` — address verification (Agent 6)
- `SARVAM_API_KEY` — Hindi voice (Agent 5 audio, Agent 7 phone call)
- `TWILIO_*` — real outbound verification call (Agent 7). This one **actually
  places a phone call**, so only needed if you specifically want to test that.

## 3. Start everything

```bash
docker compose up -d
```

First run takes a while (10-20+ min) — it's downloading and building ML models
(SAM2, CLIP, ResNet-50, Stable Diffusion) into the backend image, which is
several GB. Subsequent starts are fast (seconds).

Check it's healthy:

```bash
curl http://localhost:8000/health
```

You should see `"status":"ok"` with real product/buyer/order counts.

## 4. Open it

| What | URL |
|---|---|
| Storefront (buyer-facing shop) | http://localhost:3000 |
| Seller portal | http://localhost:3000/seller |
| Admin console (seeded `ADMIN-001` account only) | http://localhost:3000/admin |
| Backend API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

Sign up as a buyer or seller from the storefront — auth is real (JWT + bcrypt),
so create your own account rather than trying to guess a password for the
seeded demo accounts.

## 5. What to actually look at

- **Browse products** — 500+ real seeded products across 10 categories.
- **Add to cart, checkout** — real cart persistence, real order creation (COD
  or Razorpay sandbox if that key's set).
- **Ask a product question** (voice icon on a product page) — this hits Agent 5:
  real Pinecone RAG grounding + Gemini/Groq reasoning + real Sarvam Hindi voice
  synthesis. Try the mic button to ask by voice too.
- **Post a review** — publishes to a real Redis Streams event, which
  automatically triggers Agent 4 (CLIP + BERT) in the background to check if
  the review photo actually matches the product — no manual button needed.
- **Seller portal → Add Product** — upload 2-4 product photos plus 1-2 dedicated
  catalogue/label/tag photos and hit "Initialize listing & extract specs" to
  trigger Agent 1 (real SAM2 segmentation + image generation) and Agent 2 (real
  OCR across every uploaded photo, CLIP/ResNet as a fallback only for whatever
  the label didn't print). This one's slow (real CPU/API inference, can take
  minutes) — that's expected, not a bug. The Finalize screen's spec fields are
  read-only/auto-filled from what Agent 2 actually found, not editable by hand.
- **Size recommendation** — Agent 3, real Pinecone-grounded cross-seller size
  translation.

## 6. Things that need extra setup (safe to skip)

- **Agent 7's real phone call** needs a public tunnel (ngrok) pointing at your
  `localhost:8000`, since Twilio can't reach your machine directly. Skip this
  unless you specifically want to test it — everything else works without it.
- **DigiLocker seller KYC** has no key configured by default — it'll honestly
  show "not configured" rather than fake a pass. That's intentional.

## Troubleshooting

- **"Cannot connect to Docker daemon"** — Docker Desktop isn't running, start it.
- **Port already in use** — something else on your machine is using 3000, 5432,
  6379, or 8000. Stop it, or edit the port mappings in `docker-compose.yml`.
- **Backend keeps restarting** — check logs: `docker compose logs backend --tail 50`.
  Usually a missing/malformed `.env` value.
- **Want to reset all data** — `docker compose down -v` wipes the Postgres/Redis
  volumes, then `docker compose up -d` reseeds fresh.

## Stopping

```bash
docker compose down
```

Add `-v` to also wipe the database volumes if you want a clean slate next time.
