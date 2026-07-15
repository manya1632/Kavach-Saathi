# Playwright E2E suite

Real browser tests against a real backend + Postgres + Redis (either `docker compose
up`, or the host dev servers pointed at the same database). Unlike the pytest suite,
these don't mock anything at the network boundary — they drive the actual UI.

```bash
npx playwright install --with-deps chromium   # first time only
npm run e2e
```

Set `E2E_BASE_URL` if the frontend isn't on the default `http://localhost:3000`.

## What's covered

- **buyer-journey.spec.js** — signup → browse → add to cart → verify address (real
  Agent 6 Google Maps call) → place a real order (`POST /v1/orders`), asserting the
  success screen shows the actual order ID just created, not a hardcoded golden one.
- **seller-journey.spec.js** — signup → submit a real listing with a photo upload,
  asserting Agent 1/2's real async pipeline was genuinely queued.
- **admin-console.spec.js** — admin login + real analytics/fraud-cases data, and that
  a buyer's valid-but-wrong-role session can't reach the console.

## What's intentionally not covered here

- Agent 1/2's listing pipeline is only verified as far as "queued and polling" — the
  real SAM2/CLIP/ResNet-50/Stable Diffusion inference takes real CPU minutes, which
  would make this suite too slow to run routinely. The full real run is covered by
  `tests/test_catalogue_agent_integration.py` (mocked at the heavy-model boundary,
  DB/response contract verified for real) and the manual walkthrough in
  `../../RUNBOOK.md`.
- Agent 7's real Twilio call and Agent 8's return-video upload aren't driven through
  the browser here — they're covered by `tests/test_delivery_confirmation.py` /
  `tests/test_api_workflows.py::test_return_threshold_paths` and RUNBOOK.md's manual
  walkthrough, since both need real external state (a phone, a video file) a browser
  automation script can't provide.
