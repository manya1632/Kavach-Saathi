# The Eight Agents

Every agent below calls real models or real external APIs when its provider is
configured, and degrades honestly (a documented fallback, never a fabricated result)
when it isn't. "Honest degrade" is called out explicitly per agent. Source files:
`src/kavach_saathi/agents/*.py`, providers in `src/kavach_saathi/providers/*.py`.

## Agent 1 — Catalogue Truth Guardian

**File:** `agents/catalogue.py` · **Trigger:** `POST /v1/listings/analyze` (queued)

- **Image generation:** SAM 2.1 (`facebook/sam2.1-hiera-tiny`, self-hosted) segments
  the garment from the seller's photo, then a five-stage provider cascade
  (`providers/catalogue_generation.py`) generates each front/back/left/right catalogue
  view: FASHN's paid Try-On API (first-party, metered, no cold starts) → Nano Banana 2
  (Gemini image generation, gated on a Redis-tracked daily quota,
  `nano_banana_quota:{date}`) → the free FASHN Hugging Face Space → Hugging Face
  Inference API (FLUX.1 Kontext) → a self-hosted Stable Diffusion + ControlNet
  (`diffusers`) last resort, all conditioned on the same SAM-segmented garment cutout.
  The `provider` field on each generated view (`fashn_api`, `nano_banana_2`,
  `fashn_vton`, `huggingface_flux_kontext`, or `stable_diffusion_controlnet`) records
  which one actually served the request. Not applicable to non-garment products (bags,
  footwear, jewellery) — there's no "model wearing it" to generate, so the seller's own
  uploaded photos are used as the catalogue images as-is.
- **Image quality:** real OpenCV computation (`providers/image_quality.py`) — Laplacian
  blur variance, resolution, brightness — combined into a 0–1 score. No API key
  required.
- **Stolen-photo check:** real Google Cloud Vision Web Detection
  (`providers/stolen_photo.py`), config-gated on `GOOGLE_VISION_API_KEY` -- a plain
  REST API key, not a service account; the same project as `GOOGLE_MAPS_API_KEY` works
  once Cloud Vision API is enabled on it.
  **Honest degrade:** without that credential, `GoogleVisionUnavailable` is raised and
  caught — the product is never flagged as stolen without an actual check having run
  (a false "not flagged" is the only possible unconfigured outcome, never a false
  accusation), and `reverse_search_error` in the evidence records why.

## Agent 2 — Honest Spec Enforcer

**File:** `agents/specs.py` · **Trigger:** part of `POST /v1/listings/analyze`

- **OCR/label extraction:** a Groq-first cascading reasoning provider (Groq vision →
  Gemini fallback) reads every image the seller uploaded — both the plain product
  photo and the dedicated catalogue/label/tag photo — for fabric/GSM/color/care-label
  text.
- **CV as fallback, not a challenger:** CLIP (`openai/clip-vit-base-patch32`) +
  ResNet-50 (self-hosted) independently infer fabric/color from the product photo, but
  only ever *fill in* a field the label genuinely didn't print (e.g. color is almost
  never printed on a care label at all) — they never override or flag a conflict
  against a value OCR actually read off the label, since a printed label is ground
  truth, not a claim to be second-guessed by a rough zero-shot CV guess.
  GSM/wash-care have no CV signal at all; if the label doesn't print them, they're left
  absent rather than a fabricated value.
- **Honest degrade:** if the reasoning provider is unavailable, OCR fields fall back to
  `label_visible=False` and the CV-only signal (or, for non-garment products, just
  material+color) is used instead — the label is never claimed as read when it wasn't.
- Missing/conflicting fields produce a dynamic form; resubmission via
  `POST /agents/spec-enforcer/submit-missing`.

## Agent 3 — Cross-Seller Size Translator

**File:** `agents/size.py` · **Trigger:** `POST /v1/size/recommend` (sync), or as part
of `POST /v1/voice/query` when the question is size-related

- Pinecone vector index (`kavach-saathi-size-rag`) holds embedded brand size charts and
  buyer purchase/fit history; the reasoning provider reasons over the retrieved context
  to produce a recommendation localized to `preferred_language`.
- **Honest degrade:** `PineconeUnavailable`/`ReasoningUnavailable` fall back to a
  deterministic measurement-based rule, with the fallback reason recorded in evidence.

## Agent 4 — Image-Truth Review Filter

**File:** `agents/review.py` · **Trigger:** automatic on the `review.submitted` Redis
Streams event (published by `POST /v1/reviews`); `POST /v1/reviews/analyze` is a manual
re-check convenience

- CLIP image-text similarity (does the photo match the product?) + a multilingual BERT
  text-relevance classifier (`providers/review_vision.py`), both real, both computed —
  not the old `expected_relevant` fixture read.
- Written review text is always retained; only the photo is hidden (`hide_media`
  action) when the image doesn't match.

## Agent 5 — Trusted Voice Q&A

**File:** `agents/voice.py` · **Trigger:** `POST /v1/voice/query` (sync)

- Sarvam AI real ASR (`saarika:v2.5`) transcribes a buyer's spoken Hindi/English
  question when audio is provided; Sarvam TTS (`bulbul:v3`, speaker `priya`) synthesizes
  the spoken answer.
- Pinecone RAG (`kavach-saathi-voice-qa` index) grounds the answer in real order,
  review, and product-spec evidence. A learning loop embeds resolved Q&A pairs back
  into the same index. Supports comparing multiple products in one question
  (`product_ids[]`).
- **Honest degrade:** without Sarvam/Pinecone/reasoning credentials, falls back to
  deterministic Hindi/English template answers built from verified label data — no
  audio is fabricated, and `rag_error` records why grounding didn't run.

## Agent 6 — Address Guardian

**File:** `agents/address.py` · **Trigger:** `POST /v1/address/verify` (sync), also
re-invoked on an `update_address` decision from Agent 7's confirmation flow

- Real Google Maps Geocoding API (`providers/google_maps.py`) reverse-geocodes the
  buyer's browser coordinates. IndicNLP (`indic-nlp-library`) normalizes Devanagari (or
  other Indic-script) raw address text before the postal-PIN cross-check.
- India Post's reference DIGIPIN algorithm (`digipin.py`) — a pure offline
  computation, was already real before this rewrite.
- **Honest degrade:** without `GOOGLE_MAPS_API_KEY`, the postal PIN genuinely cannot be
  cross-checked — this routes to `needs_evidence` (manual confirmation) rather than
  silently reporting a match, since a fabricated "PIN matches" here would be a false
  positive with real delivery consequences.

## Agent 7 — Delivery Confirmation

**File:** `agents/confirmation.py` · **Trigger:** automatic on the `order.placed` Redis
Streams event; `POST /v1/orders/{order_id}/confirm-simulated` is a manual
checkout-flow convenience

- Real Twilio Programmable Voice places an outbound call. The confirmation question is
  pre-generated as audio via Sarvam TTS *before* the call is placed (not inside the
  webhook — an earlier version did this synchronously in the webhook and raced
  Twilio's timeout) and served over `PUBLIC_BASE_URL`; without a public URL, Twilio's
  own `<Say language="hi-IN">` is used instead — still a real spoken call, just not
  Sarvam's voice.
- Twilio `<Record>` captures the buyer's spoken reply; Sarvam ASR transcribes it; the
  reasoning provider classifies intent (`confirmed`/`reschedule`/`cancel`/`unclear`)
  with up to 3 retries on a transcription/classification failure.
- After `AGENT7_MAX_RETRIES` unanswered/unclear attempts, falls back to a real Twilio
  WhatsApp message (sandbox number) — never fabricates a call outcome that didn't
  happen.
- **Honest degrade:** without Twilio credentials or `PUBLIC_BASE_URL`, `initiate_call`
  reports "not configured" rather than pretending a call was placed.

## Agent 8 — Return Authenticity Verifier

**File:** `agents/return_verifier.py` · **Trigger:** `POST /v1/returns/analyze` (queued)

- Real OpenCV frame extraction from the buyer's return video, CLIP + ResNet-50
  embedding similarity (averaged across both models) against the product's real
  catalogue image (`providers/return_vision.py`).
- The reasoning provider reads the best-matching frame for visible
  label/tag/fabric text, cross-checked against the product's listed fabric.
- The resulting decision (`approve`/`request_more_evidence`/`manual_inspection`) is
  persisted as a real `returns` row and stamped onto the order's `return_outcome`
  (`repository.record_return_decision`) — previously computed but never written
  anywhere — which immediately feeds `trust_jobs.py`'s seller/buyer trust-score
  recompute.
- **Honest degrade:** if the reasoning provider is unavailable, `label_matches` falls
  back to `False` rather than assuming a match; the CLIP/ResNet score alone still
  drives the decision.

## Cross-cutting: the reasoning provider cascade

Agents 1, 2, 3, 5, 7, and 8 all read from the same `CascadingReasoningProvider`
(`providers/reasoning.py`): Gemini first, Groq second (a real infrastructure-level
fallback, not a retry of the same failure — see `docs/architecture.md`). Image-bearing
calls route Groq to `meta-llama/llama-4-scout-17b-16e-instruct` specifically, since
Groq's default text model can't read images. With neither key configured, every agent
above falls back to its own documented deterministic/rule-based path and reports why —
none of them fabricate a model response.
