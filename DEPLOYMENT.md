# Kavach Saathi — Free-Cost Deployment Plan

Status: plan only, no code changes required. Verified against current (July 2026) provider terms.

---

## 1. What actually needs to be deployed

From the repo analysis (`docker-compose.yml`, `docs/architecture.md`, `pyproject.toml`):

| Component | What it is | Resource profile |
|---|---|---|
| `frontend` | Next.js 16 storefront (`web/`), rewrites `/agent-api/*` to backend | Light, mostly static/SSR |
| `backend` | FastAPI (`kavach_saathi.app`), sync API + queues agent workflows | Heavy image (~8–10 GB: torch, transformers, diffusers) |
| `worker` | `kavach_saathi.event_worker` — Redis Streams consumer, runs Agents 4/7 | Same image; loads CLIP/BERT/SAM2/Stable Diffusion on CPU; multi-GB HF model cache; jobs run seconds-to-minutes |
| `postgres` | Postgres 16, 26 tables, Alembic migrations | Small (<1 GB data for demo) |
| `redis` | Cache + Redis Streams event bus (XREADGROUP consumer groups) | Small |
| Media | S3-compatible storage already supported via `MEDIA_*` env vars | ~GBs of images |
| Webhooks | Twilio voice/WhatsApp + Razorpay need a public HTTPS `PUBLIC_BASE_URL` | Always-on URL required |

Key constraints this imposes:

- The backend/worker **cannot run on serverless free tiers** (Lambda, Cloud Run free, Vercel functions): the image alone exceeds or nearly exceeds limits, model load takes minutes → catastrophic cold starts, and jobs run longer than most function timeouts. The `mangum`/`template.yaml` Lambda path exists in the repo but `docs/architecture.md` itself says it is not the supported path.
- Redis Streams with blocking consumer-group reads runs 24/7 → a serverless Redis free tier metered per-command (Upstash: 500K commands/month) would be burned by the worker's polling. Redis should live next to the worker.
- "Minimal cold starts" + "always-on webhooks" ⇒ the backend must be an **always-on server**, not scale-to-zero.

---

## 2. Verdict on "different things in different new AWS accounts with free credits"

**Do not do this. It is explicitly against AWS's terms and it also wouldn't work economically.**

1. **ToS violation.** AWS Free Tier terms state you are ineligible for offers if you or your entity "create(s) more than one account to receive additional benefits under the Offers", and that credits are only for customers who have never had an AWS account. Detected duplicate accounts (same card, phone, address, device) get credits revoked and accounts suspended — mid-demo, with your data inside.
2. **The credits are small and short-lived.** Since July 2025, a new AWS account gets $100 on signup + up to $100 via onboarding activities, and the **free plan hard-expires after 6 months** (or when credits run out, whichever is first). An always-on box big enough for this stack (≥8 GB RAM, e.g. `t3.large` ≈ $60+/mo in ap-south-1) would eat $200 in ~3 months — per account. You'd be rotating accounts forever, migrating Postgres data each time, breaking webhook URLs each time.
3. **Splitting services across accounts adds latency and failure modes** (cross-account networking over public internet), the opposite of "scalable and fast".

**Legitimate use of AWS free credits:** one single AWS account (if you've never had one) is fine as a *supplement* — e.g. temporary burst capacity for a demo day — but not as the permanent home.

---

## 3. Recommended architecture (all free, always-on, zero cold starts)

```
Browser ──> Vercel (Next.js frontend, global CDN)  [free Hobby plan]
                │  /agent-api/* rewrite
                ▼
        https://api.<your-name>.duckdns.org        [free DNS + free TLS]
                │
                ▼
     Oracle Cloud Always-Free Ampere A1 VM (ARM, 2 OCPU / 12 GB RAM / up to 200 GB disk)
     └─ Caddy (reverse proxy, auto-HTTPS)
     └─ docker compose: backend + worker + postgres + redis   (your existing compose file)
                │
                ▼
     Cloudflare R2 (S3-compatible media storage) [free: 10 GB storage, ZERO egress fees]
     Twilio / Razorpay / Gemini / Groq / Pinecone / Sarvam → already free/sandbox tiers
```

Why this wins on every stated requirement:

- **Free forever, not free-for-6-months.** Oracle's Always Free tier has no expiry (unlike AWS credits). Note: as of June 15, 2026 Oracle quietly halved the free Ampere allowance from 4 OCPU/24 GB to **2 OCPU/12 GB** — still by far the largest permanently-free compute anywhere, and enough for this stack with the tuning in §5.4.
- **Zero cold starts.** The VM runs 24/7. Models stay warm in the HF cache volume (your compose file already does this). Vercel serves the frontend from CDN edge.
- **Fast.** Pick the Mumbai (`ap-mumbai-1`) or Hyderabad Oracle region → single-digit-ms latency to Indian users, same region as your `AWS_REGION=ap-south-1` assumption. R2 has zero egress fees, so serving product images is free and CDN-cacheable.
- **Scalable path exists without re-architecture.** Frontend already scales infinitely on Vercel's CDN. When you outgrow the VM, you flip Oracle to Pay-As-You-Go and resize the same instance (larger A1 shapes are extremely cheap, ~$0.01/OCPU-hr), or point `DATABASE_URL` at a managed Postgres. No code changes at any step — the app is already env-var-driven.
- **No code changes now.** Everything below is accounts, env vars, and shell commands.

### Free-tier budget check

| Service | Free allowance | Your usage |
|---|---|---|
| Oracle A1 VM | 2 OCPU, 12 GB RAM, 200 GB block storage, 10 TB egress/mo | backend+worker+pg+redis ≈ fits with swap (§5.4) |
| Vercel Hobby | 100 GB bandwidth, 1M edge requests/mo | demo traffic ≪ limits (Hobby = non-commercial; fine for a prototype/demo) |
| Cloudflare R2 | 10 GB storage, 1M class-A + 10M class-B ops/mo, $0 egress | product/review media ≪ limits |
| DuckDNS | free subdomain forever | 1 subdomain |
| Let's Encrypt (via Caddy) | free TLS, auto-renewed | 1 cert |
| UptimeRobot | 50 monitors free | keep-alive + alerting |
| GitHub Actions | 2,000 min/mo free | CI already in `.github/workflows/ci.yml` |

---

## 4. Detailed step-by-step

### Phase 0 — Accounts (Day 1)

1. **Oracle Cloud**: sign up at cloud.oracle.com/free. **Choose home region carefully — it cannot be changed.** Pick `ap-mumbai-1` (or Hyderabad). Card is for identity verification only; Always Free never charges. Tip: A1 capacity in popular regions is sometimes "out of capacity" for free-tier signups — if instance creation fails, retry at off-peak hours or use a script-retry; upgrading to Pay-As-You-Go (still $0 for Always-Free shapes, and reportedly keeps the old 4 OCPU/24 GB allowance) removes the capacity queue.
2. **Cloudflare**: free account → R2 (needs a card on file for R2 but free tier bills $0).
3. **DuckDNS** (duckdns.org): claim `kavach-saathi.duckdns.org` (or similar), note the token.
4. **Vercel**: free Hobby account, connect your GitHub repo.
5. Keep existing keys: Gemini, Groq, Pinecone, Sarvam, Twilio trial, Razorpay sandbox, Gmail SMTP app password — all already free tiers you use locally.

### Phase 1 — Provision the VM

1. Create instance: **VM.Standard.A1.Flex — 2 OCPU, 12 GB RAM**, Ubuntu 24.04 (aarch64), boot volume **150–200 GB** (free block storage total is 200 GB; models + Docker images + Postgres need room).
2. In the VCN security list, allow ingress TCP **22, 80, 443** only. Do **not** expose 5432/6379/8000 publicly.
3. SSH in, then:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
   sudo usermod -aG docker $USER   # re-login
   # 8 GB swap — critical headroom for CPU model inference on 12 GB RAM
   sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   # Oracle Ubuntu images ship restrictive iptables rules; open 80/443 locally too
   sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
4. Point DuckDNS at the VM's public IP (their one-line cron installer keeps it updated).

### Phase 2 — Deploy the stack

1. `git clone` the repo onto the VM.
2. Create production `.env` from `.env.example`. Changes vs local:
   - `JWT_SECRET` → long random value (`openssl rand -hex 32`)
   - `FRONTEND_ORIGIN=https://<your-app>.vercel.app` (CORS)
   - `PUBLIC_BASE_URL=https://kavach-saathi.duckdns.org` (Twilio webhooks)
   - `MEDIA_STORAGE_BACKEND` + `MEDIA_ENDPOINT_URL`/`MEDIA_ACCESS_KEY_ID`/`MEDIA_SECRET_ACCESS_KEY`/`MEDIA_PUBLIC_BASE_URL` → R2 bucket credentials (R2 is S3-compatible; endpoint is `https://<account-id>.r2.cloudflarestorage.com`). Enable the bucket's public dev URL or a custom domain for `MEDIA_PUBLIC_BASE_URL`.
   - `DEPLOYMENT_ENVIRONMENT=production`, `ALLOW_DEMO_OTP` per your demo needs.
   - Strong Postgres password; mirror it in the compose `DATABASE_URL`.
3. Build and start (first ARM build compiles/downloads for ~20–40 min):
   ```bash
   docker compose build
   docker compose up -d postgres redis
   docker compose run --rm backend alembic upgrade head
   docker compose run --rm backend python scripts/generate_seed_data.py   # if you want seed data
   docker compose up -d
   ```
   Note: the images build fine on aarch64 — PyTorch publishes CPU aarch64 wheels; if the pinned `--index-url .../whl/cpu` lacks an aarch64 wheel for the pinned version, plain PyPI `torch` is CPU-only on ARM anyway (no CUDA builds exist for it), so worst case you build with the default index. No source changes needed.
4. **Caddy** as TLS reverse proxy (simplest: install on host):
   ```bash
   sudo apt install -y caddy
   # /etc/caddy/Caddyfile
   # kavach-saathi.duckdns.org {
   #     reverse_proxy localhost:8000
   # }
   sudo systemctl reload caddy
   ```
   Caddy fetches/renews the Let's Encrypt cert automatically. Your backend is now at `https://kavach-saathi.duckdns.org`.
5. Warm the models once (trigger one listing analysis / review check) so the HF cache volume is populated — after this, no download ever happens again → no "cold start" on agent runs.

### Phase 3 — Frontend on Vercel

1. In Vercel, import the repo, set **Root Directory = `web/`**, framework auto-detects Next.js.
2. Environment variable: `AGENT_API_ORIGIN=https://kavach-saathi.duckdns.org` (the value `next.config.mjs` uses for the `/agent-api/*` rewrite).
3. Deploy. Every git push now auto-deploys the frontend. The rewrite proxies API calls through Vercel's edge — CORS stays simple and the API origin is hidden.

### Phase 4 — Webhooks and external services

1. **Twilio console**: set voice/WhatsApp webhook URLs to `https://kavach-saathi.duckdns.org/...` (the paths your Twilio provider modules expose). Trial account limits (verified numbers only) are unchanged; Email-OTP via Gmail SMTP remains the free fallback exactly as documented in `.env.example`.
2. **Razorpay sandbox**: set the webhook to the public URL, keep `RAZORPAY_WEBHOOK_SECRET` in `.env`.
3. **UptimeRobot**: monitor `https://kavach-saathi.duckdns.org/v1/...` health endpoint + the Vercel URL; alerts to your email.

### Phase 5 — Operations

1. **Backups (free)**: nightly cron on the VM —
   ```bash
   docker compose exec -T postgres pg_dump -U kavach kavach_saathi | gzip > /backups/$(date +%F).sql.gz
   ```
   then sync to R2 with `rclone` (free). Use `scripts/verify_backup.ps1` to validate local backup integrity.
2. **Deploys**: `git pull && docker compose build && docker compose up -d` — or add a GitHub Actions job that SSHes in and runs exactly that on push to `main` (repo already has Actions CI).
3. **Log/rotation**: `docker compose logs` + json-file log rotation (`max-size: 10m`) in a compose override.

---

## 5. Performance, cold starts, and scaling

### 5.1 Cold starts: eliminated by design
- VM never sleeps; uvicorn + worker are resident processes.
- HF model cache is a persistent volume → model weights load from local disk, never re-download.
- Vercel CDN serves static assets instantly worldwide; SSR functions have sub-second cold starts and your traffic keeps them warm.
- This is exactly why Neon/Supabase free Postgres was **not** chosen: their free tiers autosuspend after ~5 min idle → 500ms–2s wake-up latency on first query. Local Postgres on the VM = 0.

### 5.2 Memory plan for 12 GB RAM + 8 GB swap
- Postgres + Redis ≈ 0.7 GB; uvicorn backend ≈ 1–2 GB resident; worker with CLIP+BERT loaded ≈ 3–4 GB; Stable Diffusion inference peaks are what the swap absorbs.
- Keep the compose file's existing `OMP_NUM_THREADS=2` / worker split (`RUN_EVENT_CONSUMERS_IN_WEB=false`) exactly as-is — it was designed for this.
- If SD image generation is too slow/heavy on 2 OCPU, prefer the Gemini image path (`GEMINI_IMAGE_MODEL`) which the code already treats as primary, with SD as fallback — an env/keys decision, not a code change.

### 5.3 Speed for Indian users
- Oracle Mumbai region + Vercel's Mumbai edge PoP + R2 with Cloudflare's India PoPs → all three legs are in-country.

### 5.4 Scaling path (when free isn't enough)
1. **Flip Oracle to Pay-As-You-Go** (keeps free allowance, removes capacity limits): resize the same A1 instance to 4 OCPU/24 GB — per current reports this may still be $0, worst case ~$15/mo. Nothing redeploys; it's a reboot.
2. Split worker to a second VM (compose already separates it; point both at the same `REDIS_URL`/`DATABASE_URL`).
3. Move Postgres to managed (Neon paid/RDS) by changing `DATABASE_URL`.
4. Frontend needs nothing — Vercel scales it automatically (upgrade to Pro if it becomes commercial).

---

## 6. Fallback options (if Oracle A1 capacity is unavailable in your region)

| Option | Cost | Trade-off |
|---|---|---|
| Oracle PAYG upgrade (still Always-Free shapes) | $0 | removes the free-tier capacity queue; card must be chargeable |
| **One** legit AWS free account: `t4g.large` on the $100–200 credits | $0 for ~2–3 mo | expires ≤6 months; migration required after; single account only — no multi-account farming |
| Hetzner CAX21 (ARM, 4 vCPU/8 GB) | ~€6/mo | cheapest reliable paid option, EU regions only |
| Contabo VPS (Mumbai region available) | ~$6/mo | budget option with an India location |

---

## 7. Explicit answers to your questions

- **"Deploy different things in different new AWS accounts with free credits — verify this."** Verified: prohibited by AWS Free Tier terms (one account per customer; multi-account credit farming = credit revocation/suspension), and the credits ($100–$200) with a 6-month free-plan cap couldn't sustain this stack anyway. Rejected — see §2.
- **"Free of cost."** Yes: Oracle Always Free (permanent) + Vercel Hobby + R2 + DuckDNS + Let's Encrypt + existing free API tiers. $0/month, no expiry.
- **"Scalable and fast as possible."** CDN-served frontend, in-region always-on backend, warm model cache, zero-egress media, and a documented no-rearchitecture scale path (§5.4).
- **"Minimal cold starts."** Zero for API, DB, Redis, and models; near-zero for frontend (§5.1).
- **"No code changes."** None required — every step is accounts, env vars, DNS, and shell commands. The repo's own `docker-compose.yml`, `.env.example`, and `MEDIA_*` abstraction already anticipate exactly this deployment.
