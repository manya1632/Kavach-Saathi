from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from sqlalchemy.orm import Session

from kavach_saathi.admin_api import router as admin_router
from kavach_saathi.auth import (
    AuthError,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_current_user,
    rotate_refresh_token,
    signup_user,
)
from kavach_saathi.commerce_api import router as commerce_router
from kavach_saathi.config import Settings, get_settings
from kavach_saathi.container import Container, get_container
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import User
from kavach_saathi.events import start_order_consumer, start_review_consumer
from kavach_saathi.models import (
    AddressVerifyRequest,
    AuthUser,
    HealthResponse,
    ListingAnalyzeRequest,
    LoginRequest,
    PresignRequest,
    PresignResponse,
    RefreshRequest,
    ReturnAnalyzeRequest,
    ReviewAnalyzeRequest,
    ReviewSummaryRequest,
    RunEnvelope,
    RunStatus,
    SignupRequest,
    SizeRecommendRequest,
    TokenResponse,
    VoiceQueryRequest,
    WorkflowType,
)
from kavach_saathi.orchestration.service import RunNotFoundError
from kavach_saathi.repository import DataNotFoundError
from kavach_saathi.seller_api import router as seller_router
from kavach_saathi.specs_api import router as specs_router

STOREFRONT_CATEGORIES = [
    "Popular",
    "Kurti, Saree & Lehenga",
    "Women Western",
    "Lingerie",
    "Men",
    "Kids & Toys",
    "Home & Kitchen",
    "Beauty & Health",
    "Jewellery & Accessories",
    "Bags & Footwear",
]

def _run_workflow_in_background(coro_factory) -> None:
    """Execute an agent workflow coroutine on a dedicated thread with its own event
    loop, fully detached from the request's async context.

    A plain `asyncio.create_task()` here is not reliable: it schedules on the request's
    current event loop, and ASGI test/dev transports (and some ASGI servers) tear down
    or cancel that loop's pending tasks once the request's own coroutine returns --
    which would silently kill Agent 1/2/4/8's real, multi-second-to-multi-minute model
    calls mid-run. A dedicated thread + its own `asyncio.run()` survives independently
    of the originating request's lifecycle, which is what "the frontend polls
    GET /runs/{run_id} while a real model runs in the background" actually requires.
    """

    def _run() -> None:
        try:
            asyncio.run(coro_factory())
        except Exception:
            # A webhook-triggered background task (e.g. Agent 7's Twilio callbacks)
            # has no caller left to see a raised exception -- without this, a failure
            # here is entirely silent (no log line, no agent_logs row), which is
            # exactly the kind of unobservable failure this project's honesty rule
            # exists to prevent.
            logging.getLogger(__name__).exception("Background workflow task failed")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Typed orchestration API for eight Kavach Saathi commerce agents.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.asset_dir.exists():
        app.mount("/mock-assets", StaticFiles(directory=settings.asset_dir), name="mock-assets")

    @app.get("/", include_in_schema=False)
    async def frontend():
        return RedirectResponse(settings.frontend_origin)

    @app.exception_handler(DataNotFoundError)
    async def data_not_found(_: Request, exc: DataNotFoundError):
        return Response(
            content=json.dumps({"detail": str(exc)}),
            status_code=404,
            media_type="application/json",
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(
        cfg: Settings = Depends(get_settings), container: Container = Depends(get_container)
    ) -> HealthResponse:
        summary = container.repository.summary()
        return HealthResponse(
            status="ok" if summary.get("products", 0) else "degraded",
            mode=cfg.app_mode,
            checks={
                "seed_data": bool(summary.get("products")),
                "reasoning": "groq" if cfg.uses_groq else "deterministic",
                "reasoning_model": cfg.groq_model if cfg.uses_groq else "fixture-rules",
                **summary,
            },
        )

    prefix = settings.api_prefix

    def _auth_user(user: User) -> AuthUser:
        return AuthUser(
            id=user.id,
            role=user.role,
            name=user.name,
            email=user.email,
            phone=user.phone,
            preferred_language=user.preferred_language,
        )

    @app.post(f"{prefix}/auth/signup", response_model=TokenResponse, status_code=201)
    async def auth_signup(
        payload: SignupRequest,
        cfg: Settings = Depends(get_settings),
        session: Session = Depends(get_session),
    ) -> TokenResponse:
        user = signup_user(
            role=payload.role,
            name=payload.name,
            password=payload.password,
            preferred_language=payload.preferred_language,
            email=payload.email,
            phone=payload.phone,
            business_name=payload.business_name,
            session=session,
        )
        access = create_access_token(user, cfg)
        refresh = create_refresh_token(user, session, cfg)
        return TokenResponse(access_token=access, refresh_token=refresh, user=_auth_user(user))

    @app.post(f"{prefix}/auth/login", response_model=TokenResponse)
    async def auth_login(
        payload: LoginRequest,
        cfg: Settings = Depends(get_settings),
        session: Session = Depends(get_session),
    ) -> TokenResponse:
        user = authenticate_user(identifier=payload.identifier, password=payload.password, session=session)
        access = create_access_token(user, cfg)
        refresh = create_refresh_token(user, session, cfg)
        return TokenResponse(access_token=access, refresh_token=refresh, user=_auth_user(user))

    @app.post(f"{prefix}/auth/refresh", response_model=TokenResponse)
    async def auth_refresh(
        payload: RefreshRequest,
        cfg: Settings = Depends(get_settings),
        session: Session = Depends(get_session),
    ) -> TokenResponse:
        user, access, refresh = rotate_refresh_token(payload.refresh_token, session, cfg)
        return TokenResponse(access_token=access, refresh_token=refresh, user=_auth_user(user))

    @app.get(f"{prefix}/auth/me", response_model=AuthUser)
    async def auth_me(user: Annotated[User, Depends(get_current_user)]) -> AuthUser:
        return _auth_user(user)

    @app.patch(f"{prefix}/auth/language", response_model=AuthUser)
    async def auth_update_language(
        language: Annotated[str, Query(min_length=2, max_length=8)],
        user: Annotated[User, Depends(get_current_user)],
        session: Session = Depends(get_session),
    ) -> AuthUser:
        db_user = session.get(User, user.id)
        db_user.preferred_language = language
        session.flush()
        return _auth_user(db_user)

    @app.exception_handler(AuthError)
    async def auth_error_handler(_: Request, exc: AuthError):
        return Response(
            content=json.dumps({"detail": exc.detail}),
            status_code=exc.status_code,
            media_type="application/json",
            headers=exc.headers,
        )

    app.include_router(seller_router, prefix=prefix, tags=["seller"])
    app.include_router(specs_router, prefix=prefix, tags=["spec-enforcer"])
    app.include_router(commerce_router, prefix=prefix, tags=["commerce"])
    app.include_router(admin_router, prefix=prefix, tags=["admin"])

    @app.on_event("startup")
    async def start_event_consumers() -> None:
        # Automatically invokes Agent 4 (ReviewFilterAgent) on every `review.submitted`
        # event -- the real trigger path replacing the old manual "Check review truth"
        # button (gap_report B4/Y2's event-driven requirement).
        container = get_container()
        start_review_consumer(container)
        # Automatically invokes Agent 7's real outbound Twilio call on every
        # `order.placed` event (gap_report B1).
        start_order_consumer(container)

    def storefront_product(
        product: dict,
        container: Container,
        *,
        seller: dict | None = None,
        include_gallery: bool = True,
    ) -> dict:
        seller = seller or container.repository.get("sellers", product["seller_id"])
        media_path = product["media"]["primary"].removeprefix("assets/mock/")
        original_price = product["original_price"]
        discount = round((1 - product["price"] / original_price) * 100)
        return {
            "id": product["id"],
            "name": product["name"],
            "brand": product.get("brand", "Kavach Select"),
            "category": product["category"],
            "audience": product.get("audience", "All"),
            "description": product.get("description", ""),
            "price": product["price"],
            "original_price": original_price,
            "discount_percent": discount,
            "rating": product["rating"],
            "review_count": product["review_count"],
            "stock": product.get("stock", 0),
            "delivery_days": product.get("delivery_days", 4),
            "free_delivery": product.get("free_delivery", True),
            "cod_available": product.get("cod_available", True),
            "occasion": product.get("occasion", "Everyday"),
            "material": product.get("material", product["specs"].get("fabric", "See label")),
            "highlights": product.get("highlights", []),
            "badges": product.get("badges", []),
            "presentation": product.get("presentation", {}),
            "seller": {
                "id": seller["id"],
                "name": seller["name"],
                "city": seller["city"],
                "rating": seller["rating"],
                "verified": seller["verified"],
            },
            "specs": product["specs"],
            "size_chart": product["size_chart"],
            "return_window_days": product["return_window_days"],
            "image_url": f"/mock-assets/{media_path}",
            "catalogue_images": [
                {
                    "angle": image["angle"],
                    "url": f"/mock-assets/{image['url'].removeprefix('assets/mock/')}",
                    "verified": image["verified"],
                }
                for image in (container.repository.product_images(product["id"]) if include_gallery else [])
            ] or ([
                {"angle": angle, "url": f"/mock-assets/{media_path}", "verified": False}
                for angle in ("front", "back", "left", "right")
            ] if include_gallery else []),
        }

    @app.get(f"{prefix}/storefront/products")
    async def storefront_products(
        q: str | None = None,
        category: str | None = None,
        limit: int = Query(default=500, ge=1, le=500),
        container: Container = Depends(get_container),
    ):
        products = container.repository.list("products")
        # Filter out non-active products
        products = [product for product in products if product.get("status") == "active"]

        # Sort by activation_timestamp descending
        from datetime import datetime, UTC
        min_dt = datetime.min.replace(tzinfo=UTC)

        def get_activation_time(p):
            ts = p.get("activation_timestamp")
            if not ts:
                return min_dt
            if isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts)
                except ValueError:
                    return min_dt
            return ts

        products.sort(key=get_activation_time, reverse=True)

        if q:
            term = q.casefold()
            products = [
                product
                for product in products
                if any(
                    term in str(value).casefold()
                    for value in (
                        product["name"],
                        product["category"],
                        product.get("brand", ""),
                        product.get("material", ""),
                        product.get("occasion", ""),
                    )
                )
            ]
        if category and category != "All":
            products = [product for product in products if product["category"] == category]
        sellers = {seller["id"]: seller for seller in container.repository.list("sellers")}
        active_categories = {product["category"] for product in products}
        return {
            "items": [
                storefront_product(
                    product,
                    container,
                    seller=sellers.get(product["seller_id"]),
                    include_gallery=False,
                )
                for product in products[:limit]
            ],
            "total": len(products),
            "categories": [
                item
                for item in STOREFRONT_CATEGORIES
                if item in active_categories
            ],
        }

    @app.get(f"{prefix}/storefront/products/{{product_id}}")
    async def storefront_product_detail(product_id: str, container: Container = Depends(get_container)):
        product = container.repository.get("products", product_id)
        result = storefront_product(product, container)
        result["specifications"] = container.repository.product_specifications(product_id)
        result["reviews"] = container.repository.product_reviews(product_id)
        result["review_report"] = container.repository.review_report(product_id)
        return result

    @app.get(f"{prefix}/storefront/products/{{product_id}}/similar")
    async def similar_products(product_id: str, container: Container = Depends(get_container)):
        """Returns up to 8 active and in-stock products in the same category (excluding current),
        with comparable price range (+-20%) and sorted by spec overlap and activation_timestamp DESC."""
        from datetime import datetime, UTC as _UTC
        product = container.repository.get("products", product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product_price = product.get("price", 0.0)
        product_category = product.get("category")
        product_specs = product.get("specs", {})

        all_products = container.repository.list("products")
        candidates = []
        for p in all_products:
            if p.get("id") == product_id:
                continue
            if p.get("status") != "active":
                continue
            if p.get("stock", 0) <= 0:
                continue
            if p.get("category") != product_category:
                continue
            
            price = p.get("price", 0.0)
            # Price must be within 20% range
            if abs(price - product_price) > 0.2 * product_price:
                continue
                
            candidates.append(p)

        def get_similarity_score(p):
            p_specs = p.get("specs", {})
            score = 0
            for key, val in product_specs.items():
                if key in p_specs and p_specs[key] == val:
                    score += 1
            return score

        _min_dt = datetime.min.replace(tzinfo=_UTC)

        def _activation_ts(p):
            ts = p.get("activation_timestamp")
            if not ts:
                return _min_dt
            if isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts)
                except ValueError:
                    return _min_dt
            return ts

        candidates.sort(key=lambda p: (get_similarity_score(p), _activation_ts(p)), reverse=True)
        return {"items": [storefront_product(p, container) for p in candidates[:8]]}


    async def run(
        workflow: WorkflowType,
        payload,
        container: Container,
        *,
        order_id: str | None = None,
    ) -> RunEnvelope:
        data = payload.model_dump(mode="json")
        async_workflows = {
            WorkflowType.LISTING,
            WorkflowType.REVIEW,
            WorkflowType.REVIEW_SUMMARY,
            WorkflowType.RETURN,
        }
        if workflow in async_workflows:
            record = container.service.start(
                workflow,
                data,
                idempotency_key=data.get("idempotency_key"),
            )
            if record.status != RunStatus.QUEUED:
                return container.service.envelope(record)
            if settings.is_live and settings.state_machine_arn:
                import boto3

                step_functions = boto3.client("stepfunctions", region_name=settings.aws_region)
                step_functions.start_execution(
                    stateMachineArn=settings.state_machine_arn,
                    name=str(record.run_id),
                    input=json.dumps(
                        {
                            "run_id": str(record.run_id),
                            "order_id": order_id,
                        }
                    ),
                )
            else:
                # Self-hosted async execution (no Step Functions configured). Agents
                # 1/2/4/8 can take real minutes now that they call real models, so this
                # must never block the request -- callers poll GET /runs/{run_id} or the
                # SSE event stream, per the plan's API design ("frontend must show
                # honest loading/progress states, never fake instant AI magic").
                _run_workflow_in_background(
                    lambda: container.service.resume(record.run_id, order_id=order_id)
                )
            return container.service.envelope(record)
        record = await container.service.execute(
            workflow,
            data,
            idempotency_key=data.get("idempotency_key"),
            order_id=order_id,
        )
        return container.service.envelope(record)

    @app.post(f"{prefix}/listings/analyze", response_model=RunEnvelope)
    async def analyze_listing(payload: ListingAnalyzeRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.LISTING, payload, container)

    @app.post(f"{prefix}/size/recommend", response_model=RunEnvelope)
    async def recommend_size(payload: SizeRecommendRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.SIZE, payload, container)

    @app.post(f"{prefix}/reviews/analyze", response_model=RunEnvelope)
    async def analyze_review(payload: ReviewAnalyzeRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.REVIEW, payload, container)

    @app.post(f"{prefix}/reviews/summary", response_model=RunEnvelope)
    async def summarize_reviews(payload: ReviewSummaryRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.REVIEW_SUMMARY, payload, container)

    @app.post(f"{prefix}/voice/query", response_model=RunEnvelope)
    async def voice_query(payload: VoiceQueryRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.VOICE, payload, container)

    @app.post(f"{prefix}/address/verify", response_model=RunEnvelope)
    async def verify_address(payload: AddressVerifyRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.ADDRESS, payload, container)

    @app.post(f"{prefix}/returns/analyze", response_model=RunEnvelope)
    async def analyze_return(payload: ReturnAnalyzeRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.RETURN, payload, container)

    @app.get(f"{prefix}/runs/{{run_id}}", response_model=RunEnvelope)
    async def get_run(run_id: UUID, container: Container = Depends(get_container)):
        try:
            return container.service.envelope(container.service.get(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get(f"{prefix}/runs/{{run_id}}/events")
    async def get_run_events(run_id: UUID, container: Container = Depends(get_container)):
        try:
            record = container.service.get(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

        async def stream():
            for event in record.events:
                payload = event.model_dump_json()
                yield f"id: {event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post(f"{prefix}/uploads/presign", response_model=PresignResponse)
    async def presign(
        payload: PresignRequest,
        cfg: Settings = Depends(get_settings),
    ) -> PresignResponse:
        suffix = Path(payload.filename).suffix.lower()
        key = f"uploads/{payload.kind}/{uuid4()}{suffix}"
        if cfg.is_live:
            import boto3

            url = boto3.client("s3", region_name=cfg.aws_region).generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": cfg.media_bucket,
                    "Key": key,
                    "ContentType": payload.content_type,
                },
                ExpiresIn=900,
            )
        else:
            # A relative path through the Next.js rewrite (see web/next.config.mjs's
            # `/agent-api/:path*` rule) keeps this same-origin from the browser's point
            # of view no matter what host/port the page itself was loaded from -- no
            # CORS, no guessing whether localhost:8000 or a tunnel hostname is what the
            # browser can actually reach. PUBLIC_BASE_URL is for the Twilio webhook
            # callback (a server-to-server URL Twilio's servers must reach) and must
            # not be reused here: it previously pointed browser uploads at that ngrok
            # tunnel, which fails with "Failed to fetch" whenever the tunnel isn't the
            # thing serving the page (e.g. testing directly against localhost).
            url = f"/agent-api{prefix}/mock-uploads/{key}"
        return PresignResponse(object_key=key, upload_url=url, expires_in=900)

    @app.post(f"{prefix}/twilio/voice/{{order_id}}")
    async def twilio_voice(order_id: str, container: Container = Depends(get_container)):
        agent = container.service.graphs.confirmation
        order = container.repository.get("orders", order_id)
        buyer = container.repository.get("buyers", order["buyer_id"])
        language = buyer.get("language", "hi")
        question_fragment = agent.question_twiml_fragment(order_id, language)
        twiml = agent.build_voice_twiml(order_id, language, question_fragment)
        return Response(content=twiml, media_type="text/xml")

    @app.post(f"{prefix}/twilio/recorded/{{order_id}}")
    async def twilio_recorded(order_id: str, request: Request, container: Container = Depends(get_container)):
        form = await request.form()
        recording_url = str(form.get("RecordingUrl", ""))
        agent = container.service.graphs.confirmation
        if recording_url:
            _run_workflow_in_background(lambda: agent.handle_recording(order_id, recording_url))
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?><Response>'
            '<Say language="hi-IN" voice="Polly.Aditi">धन्यवाद।</Say><Hangup/></Response>'
        )
        return Response(content=twiml, media_type="text/xml")

    @app.post(f"{prefix}/twilio/status/{{order_id}}")
    async def twilio_status(order_id: str, request: Request, container: Container = Depends(get_container)):
        form = await request.form()
        call_status = str(form.get("CallStatus", ""))
        agent = container.service.graphs.confirmation
        _run_workflow_in_background(lambda: agent.handle_call_status(order_id, call_status))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put(f"{prefix}/mock-uploads/{{object_key:path}}", status_code=status.HTTP_204_NO_CONTENT)
    async def mock_upload(
        object_key: str,
        request: Request,
        cfg: Settings = Depends(get_settings),
    ):
        if cfg.is_live:
            raise HTTPException(status_code=404)
        destination = (cfg.asset_dir / object_key).resolve()
        root = cfg.asset_dir.resolve()
        if root not in destination.parents:
            raise HTTPException(status_code=400, detail="Invalid object key")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(await request.body())
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
handler = Mangum(app, lifespan="off")
