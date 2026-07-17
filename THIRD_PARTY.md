# Third-Party Components

Kavach Saathi is built on the open-source and commercial services listed below. This
file exists so a reviewer can see, in one place, everything the codebase actually
depends on and what each dependency is used for — no hidden SaaS calls, no
undocumented model downloads.

No project-wide license is granted by this repository unless a `LICENSE` file is
added separately. Every component below remains subject to its own license; nothing
here overrides that.

## Backend (Python, see `pyproject.toml`)

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn`, `mangum` | HTTP API and ASGI server |
| `pydantic`, `pydantic-settings` | Request/response schemas and env-based config |
| `sqlalchemy`, `psycopg[binary]`, `alembic` | Postgres ORM, driver, and migrations |
| `redis` | Cache and Streams event bus (`order.placed`, `review.submitted`) |
| `pyjwt`, `bcrypt` | JWT access/refresh tokens, password hashing |
| `httpx` | Async HTTP client used by every REST-based provider integration |
| `google-genai` | Gemini reasoning (Agents 2/3/5/7) and image generation (Agent 1, "Nano Banana 2" substitute) |
| `groq` | Groq cascading-fallback reasoning; `meta-llama/llama-4-scout-17b-16e-instruct` specifically for vision-bearing OCR calls when Gemini is unavailable |
| `anthropic` | Reserved for the plan's originally-named Claude reasoning provider; not wired to a live key in this deployment (see `docs/AGENTS.md`) |
| `transformers`, `torch`, `torchvision`, `safetensors`, `accelerate` | Self-hosted CLIP (`openai/clip-vit-base-patch32`), ResNet-50 (`torchvision.models.resnet50`, ImageNet-pretrained), SAM 2.1 (`facebook/sam2.1-hiera-tiny`) — no API key required |
| `diffusers` | Stable Diffusion + ControlNet — last-resort, self-hosted fallback for catalogue image generation if every hosted provider (FASHN, Nano Banana 2, Hugging Face) is unavailable or exhausted |
| `sentence-transformers` | Text embeddings for size-chart RAG and voice Q&A learning loop |
| `opencv-python-headless`, `pillow`, `numpy` | Frame extraction, blur/resolution/brightness scoring, general image handling |
| `pinecone` | Vector index for Agent 3 (size RAG) and Agent 5 (voice Q&A RAG + learning loop) |
| `indic-nlp-library` | Devanagari/Indic-script address normalization (Agent 6) before geocoding |
| `twilio` | Real outbound Programmable Voice call + WhatsApp fallback (Agent 7) |
| `razorpay` | Sandbox prepaid checkout |
| `boto3` | AWS SDK — only exercised if `APP_MODE=live` is set (not the default deployment path; see `docs/architecture.md`) |
| `python-multipart` | Multipart form parsing for FastAPI |
| `pytest`, `pytest-asyncio`, `ruff` | Test runner and linter (dev-only) |

### External APIs called directly over HTTPS (not a pip package)

| Service | Used for | Config key |
|---|---|---|
| Google Maps Geocoding API | Reverse-geocode buyer coordinates (Agent 6) | `GOOGLE_MAPS_API_KEY` |
| Google Cloud Vision (Web Detection, plain REST + API key) | Reverse-image-search "stolen photo" check (Agent 1) | `GOOGLE_VISION_API_KEY` |
| Sarvam AI (`saarika:v2.5` STT, `bulbul:v3` TTS) | Hindi speech-to-text/text-to-speech (Agents 5 and 7) — free-tier substitute for the plan's named Bhashini, which requires an institutional SPOC (see `docs/AGENTS.md`) | `SARVAM_API_KEY` |
| DigiLocker OAuth2 | Seller KYC verification | `DIGILOCKER_CLIENT_ID` / `DIGILOCKER_CLIENT_SECRET` |
| FASHN Try-On API | First-choice provider in Agent 1's catalogue-image cascade — first-party, commercially licensed, metered virtual try-on | `FASHN_API_KEY` |
| FASHN Hugging Face Space (`fashn-ai/fashn-vton-1.5`) + Hugging Face Inference API (FLUX.1 Kontext) | Free-tier fallbacks in the same cascade, used once FASHN's paid credits or Nano Banana's quota run out | `HUGGINGFACE_API_KEY` |

## Frontend (JavaScript, see `web/package.json`)

| Package | Used for |
|---|---|
| `next` | App Router, dev server, static export, `/agent-api` rewrite proxy |
| `react`, `react-dom` | UI rendering |
| `lucide-react` | Icon set used throughout the storefront/seller/admin UIs |
| `eslint`, `eslint-config-next` | Linting (dev-only) |
| `@playwright/test` | Real-browser E2E tests against a real backend (dev-only, `web/e2e/`) |

## Self-hosted machine learning models

These run inside the backend container on CPU — no third-party inference API, no
per-call cost, but real, non-fixture computation:

| Model | Checkpoint | Used by |
|---|---|---|
| SAM 2.1 (Hiera-tiny) | `facebook/sam2.1-hiera-tiny` | Agent 1 — product segmentation before catalogue-view generation |
| CLIP | `openai/clip-vit-base-patch32` | Agent 2 (fabric/color cross-check), Agent 4 (review image-text relevance), Agent 8 (return-photo vs. catalogue-photo match) |
| ResNet-50 | `torchvision.models.resnet50`, `ResNet50_Weights.IMAGENET1K_V2` | Agent 2 (fabric classification), Agent 8 (return-photo embedding match) |
| Stable Diffusion v1.5 + ControlNet | via `diffusers` | Agent 1 fallback catalogue-view generation when the Gemini image quota is exhausted |
| `bert-base-multilingual-cased` (via `sentence-transformers`) | — | Agent 4 review text relevance |
| `all-MiniLM-L6-v2` (via `sentence-transformers`) | — | Size-chart and voice-Q&A RAG embeddings |

## Attribution

- The commerce flow was inspired by the public screen journey in
  [AshokPrjapati/Meesho-clone](https://github.com/AshokPrjapati/Meesho-clone) at commit
  `4057ed337d0d7999d07f7e261b12887c9d904ddb`. Storefront code and fixtures in this
  repository were written independently; the reference repository's retired backend
  credentials and source assets are not included.
- The DIGIPIN implementation is based on the Department of Posts reference algorithm
  and is covered by the Apache 2.0 notice in [NOTICE](NOTICE).
- See [web/ATTRIBUTION.md](web/ATTRIBUTION.md) for the storefront reference record.
