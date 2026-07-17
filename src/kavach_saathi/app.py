from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from sqlalchemy import select
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
from kavach_saathi.db.models import Order, OrderItem, OrderStatusHistory, Payment, ProductVariant, User
from kavach_saathi.delivery_api import router as delivery_router
from kavach_saathi.events import start_order_consumer, start_review_consumer
from kavach_saathi.models import (
    AddressVerifyRequest,
    AuthUser,
    ChatConversationCreate,
    ChatMessageSend,
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
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient
from kavach_saathi.redis_client import get_redis
from kavach_saathi.repository import DataNotFoundError
from kavach_saathi.seller_api import router as seller_router
from kavach_saathi.specs_api import router as specs_router

logger = logging.getLogger(__name__)


def resolve_whatsapp_order_id(form_data: dict[str, str], explicit_order_id: str | None, redis) -> str | None:
    """Resolve a quick reply to the exact outbound message before using the legacy phone fallback."""
    if explicit_order_id:
        return explicit_order_id
    from kavach_saathi.providers.twilio_integration import normalize_phone_number

    replied_to_sid = str(form_data.get("OriginalRepliedMessageSid", "")).strip()
    pending = redis.get(f"whatsapp:outbound:{replied_to_sid}") if replied_to_sid else None
    if not pending:
        sender = str(form_data.get("From", "")).removeprefix("whatsapp:").strip()
        if not sender:
            return None
        pending = redis.get(f"whatsapp:pending:{normalize_phone_number(sender)}")
    return pending.decode() if isinstance(pending, bytes) else pending

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
            # A webhook-triggered background task (for example, a Twilio callback)
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
    app.include_router(delivery_router, prefix=f"{prefix}/delivery", tags=["delivery"])

    @app.on_event("startup")
    async def start_event_consumers() -> None:
        # Automatically invokes Agent 4 (ReviewFilterAgent) on every `review.submitted`
        # event -- the real trigger path replacing the old manual "Check review truth"
        # button (gap_report B4/Y2's event-driven requirement).
        container = get_container()
        start_review_consumer(container)
        # Automatically invokes the real outbound WhatsApp confirmation on every
        # `order.placed` event (gap_report B1).
        start_order_consumer(container)

        if container.settings.warm_up_on_startup:
            import asyncio

            from kavach_saathi.model_registry import warm_up_models

            asyncio.create_task(asyncio.to_thread(warm_up_models, container.settings))

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
            ]
            or (
                [
                    {"angle": angle, "url": f"/mock-assets/{media_path}", "verified": False}
                    for angle in ("front", "back", "left", "right")
                ]
                if include_gallery
                else []
            ),
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
        from datetime import UTC, datetime

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
            "categories": [item for item in STOREFRONT_CATEGORIES if item in active_categories],
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
        from datetime import UTC as _UTC
        from datetime import datetime

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
                _run_workflow_in_background(lambda: container.service.resume(record.run_id, order_id=order_id))
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

    @app.get(f"{prefix}/products/{{product_id}}/popular-size")
    async def product_popular_size(product_id: str, container: Container = Depends(get_container)):
        container.repository.get("products", product_id)
        result = container.repository.get_product_size_popularity(product_id)
        if result is None:
            return {
                "product_id": product_id,
                "needs_guidance": True,
                "selected_size": None,
                "source": "no_order_fallback",
                "action": "open_vishwas_samvad",
            }
        return {
            "product_id": product_id,
            "needs_guidance": False,
            "selected_size": result["size"],
            "qualifying_purchases": result["qualifying_purchases"],
            "delivered_purchases": result["delivered_purchases"],
            "size_related_returns": result["size_returns"],
            "source": "product_popularity",
        }

    @app.post(f"{prefix}/reviews/analyze", response_model=RunEnvelope)
    async def analyze_review(payload: ReviewAnalyzeRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.REVIEW, payload, container)

    @app.post(f"{prefix}/reviews/summary", response_model=RunEnvelope)
    async def summarize_reviews(payload: ReviewSummaryRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.REVIEW_SUMMARY, payload, container)

    @app.post(f"{prefix}/voice/query", response_model=RunEnvelope)
    async def voice_query(payload: VoiceQueryRequest, container: Container = Depends(get_container)):
        return await run(WorkflowType.VOICE, payload, container)

    @app.post(f"{prefix}/chat/conversations", status_code=201)
    async def create_chat_conversation(
        payload: ChatConversationCreate,
        user: Annotated[User, Depends(get_current_user)],
        container: Container = Depends(get_container),
    ):
        if user.role != "buyer":
            raise HTTPException(status_code=403, detail="Only buyers can access chat")
        allowed_page_types = {
            "home",
            "product",
            "cart",
            "checkout",
            "addresses",
            "orders",
            "returns",
            "wishlist",
            "support",
        }
        if payload.page_type and payload.page_type not in allowed_page_types:
            raise HTTPException(status_code=400, detail="Unsupported page context")
        if payload.product_id:
            try:
                container.repository.get("products", payload.product_id)
            except DataNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Product not found") from exc
        if payload.order_id:
            order = container.repository.get("orders", payload.order_id)
            if order["buyer_id"] != user.id:
                raise HTTPException(status_code=403, detail="Order context is not authorized")
        if payload.return_id:
            return_record = container.repository.get("returns", payload.return_id)
            if return_record.get("buyer_id") != user.id:
                raise HTTPException(status_code=403, detail="Return context is not authorized")
        return container.repository.get_or_create_active_chat(
            user.id,
            page_route=payload.page_route,
            page_type=payload.page_type,
            product_id=payload.product_id,
            order_id=payload.order_id,
            return_id=payload.return_id,
        )

    @app.get(f"{prefix}/chat/conversations")
    async def list_chat_conversations(
        user: Annotated[User, Depends(get_current_user)], container: Container = Depends(get_container)
    ):
        if user.role != "buyer":
            raise HTTPException(status_code=403, detail="Only buyers can access chat")
        return container.repository.list_active_chats_for_user(user.id)

    @app.get(f"{prefix}/chat/conversations/{{conversation_id}}/messages")
    async def list_chat_messages(
        conversation_id: str,
        user: Annotated[User, Depends(get_current_user)],
        container: Container = Depends(get_container),
    ):
        if user.role != "buyer":
            raise HTTPException(status_code=403, detail="Only buyers can access chat")
        conversations = container.repository.list_active_chats_for_user(user.id)
        if not any(c["id"] == conversation_id for c in conversations):
            raise HTTPException(status_code=403, detail="Access denied to this conversation")
        return container.repository.list_chat_messages(conversation_id)

    @app.post(f"{prefix}/chat/conversations/{{conversation_id}}/archive")
    async def archive_chat_conversation(
        conversation_id: str,
        user: Annotated[User, Depends(get_current_user)],
        container: Container = Depends(get_container),
    ):
        if user.role != "buyer":
            raise HTTPException(status_code=403, detail="Only buyers can access chat")
        conversations = container.repository.list_active_chats_for_user(user.id)
        if not any(c["id"] == conversation_id for c in conversations):
            raise HTTPException(status_code=403, detail="Access denied to this conversation")
        container.repository.archive_chat_conversation(conversation_id)
        return {"status": "archived"}

    @app.post(f"{prefix}/chat/messages")
    async def send_chat_message(
        payload: ChatMessageSend,
        user: Annotated[User, Depends(get_current_user)],
        container: Container = Depends(get_container),
    ):
        if user.role != "buyer":
            raise HTTPException(status_code=403, detail="Only buyers can access chat")
        conversation = container.repository.get_chat_for_user(payload.conversation_id, user.id)
        if not conversation or conversation["status"] != "active":
            raise HTTPException(status_code=403, detail="Access denied to this conversation")

        if payload.idempotency_key:
            try:
                redis = get_redis()
                accepted = redis.set(
                    f"chat:submit:{user.id}:{payload.idempotency_key}",
                    "1",
                    nx=True,
                    ex=120,
                )
                if not accepted:
                    raise HTTPException(status_code=409, detail="This message is already being processed")
            except HTTPException:
                raise
            except Exception:
                pass

        voice_req = VoiceQueryRequest(
            buyer_id=user.id,
            product_id=conversation.get("product_id") or "",
            compare_product_ids=[],
            text=payload.text,
            audio_key=payload.audio_key,
            # Typed and recorded questions share one response contract: readable
            # grounded text plus Sarvam audio in the detected answer language.
            synthesize_audio=True,
            voice_flow="general",
            language=payload.language,
            page_route=conversation.get("page_route"),
            page_type=conversation.get("page_type"),
            order_id=conversation.get("order_id"),
            return_id=conversation.get("return_id"),
            idempotency_key=payload.idempotency_key,
        )

        run_record = await container.service.execute(WorkflowType.VOICE, voice_req.model_dump(mode="json"))
        res = run_record.results.get("voice_qa")
        if not res:
            raise HTTPException(status_code=500, detail="Vishwas Saathi chat reasoning failed")

        response_language = str(res.data.get("language") or "en")
        transcript = str(res.data.get("transcript") or payload.text or "").strip()

        answer_text = res.user_message.get(response_language, res.user_message["en"])

        # Persist the exchange only after the grounded workflow succeeds. This avoids
        # leaving empty/partial user messages behind when STT or reasoning fails.
        user_msg = container.repository.add_chat_message(
            payload.conversation_id,
            sender="user",
            content=transcript,
            metadata_json={
                "audio_key": payload.audio_key,
                "input_type": "audio" if payload.audio_key else "text",
                "language": response_language,
            },
        )
        assistant_msg = container.repository.add_chat_message(
            payload.conversation_id, sender="assistant", content=answer_text, metadata_json=res.model_dump(mode="json")
        )

        return {"user_message": user_msg, "assistant_message": assistant_msg}

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

    @app.post(f"{prefix}/twilio/whatsapp")
    @app.post(f"{prefix}/twilio/whatsapp/{{order_id}}")
    async def twilio_whatsapp_webhook(
        request: Request,
        order_id: str | None = None,
        cfg: Settings = Depends(get_settings),
        session: Session = Depends(get_session),
    ):
        from twilio.request_validator import RequestValidator

        form_data = await request.form()
        signature = request.headers.get("X-Twilio-Signature", "")
        if cfg.twilio_auth_token:
            callback_url = (
                f"{cfg.public_base_url.rstrip('/')}{request.url.path}"
                if cfg.public_base_url
                else str(request.url)
            )
            params = {key: value for key, value in form_data.items()}
            if not signature or not RequestValidator(cfg.twilio_auth_token).validate(
                callback_url,
                params,
                signature,
            ):
                raise HTTPException(status_code=403, detail="Invalid Twilio signature")

        provider_sid = str(form_data.get("MessageSid", "")).strip()
        action_id = str(form_data.get("ButtonPayload", "")).strip()
        if not provider_sid or not action_id:
            raise HTTPException(status_code=400, detail="A signed quick-reply ID and MessageSid are required")
        webhook_key = f"twilio:webhook:{provider_sid}"
        try:
            if not get_redis().set(webhook_key, "processing", nx=True, ex=60):
                return Response(content='<?xml version="1.0"?><Response/>', media_type="text/xml")
        except Exception:
            pass

        if not order_id:
            from kavach_saathi.providers.twilio_integration import normalize_phone_number

            sender = str(form_data.get("From", "")).removeprefix("whatsapp:").strip()
            if not sender:
                raise HTTPException(status_code=400, detail="The WhatsApp sender is required")
            try:
                order_id = resolve_whatsapp_order_id(
                    {key: str(value) for key, value in form_data.items()},
                    None,
                    get_redis(),
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail="WhatsApp routing is temporarily unavailable") from exc
            if not order_id:
                raise HTTPException(status_code=409, detail="No pending WhatsApp order was found for this sender")

        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        provider = TwilioIntegrationClient(cfg)
        phone = (order.address_snapshot or {}).get("phone")
        if phone:
            from kavach_saathi.providers.twilio_integration import normalize_phone_number

            sender = str(form_data.get("From", "")).removeprefix("whatsapp:").strip()
            if not sender or normalize_phone_number(sender) != normalize_phone_number(phone):
                raise HTTPException(status_code=403, detail="WhatsApp sender does not match this order")
        today = order.created_at.date() if order.created_at else datetime.now(UTC).date()
        outbound_message: tuple[str, dict[str, str]] | None = None

        if action_id == "order_confirm_yes" and order.status == OrderStatus.AWAITING_BUYER_CONFIRMATION:
            order.status = OrderStatus.CONFIRMED
            order.whatsapp_workflow_state = "awaiting_delivery_date_confirmation"
            if order.promised_delivery_date is None:
                offset = 3 + (int.from_bytes(order.id.encode("utf-8"), "little") % 2)
                order.promised_delivery_date = datetime.combine(today + timedelta(days=offset), datetime.min.time())
            session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.CONFIRMED, actor="buyer"))
            if phone and cfg.twilio_delivery_date_content_sid:
                outbound_message = (
                    cfg.twilio_delivery_date_content_sid,
                    {"1": order.id, "2": order.promised_delivery_date.date().isoformat()},
                )
        elif action_id == "order_confirm_no" and order.status == OrderStatus.AWAITING_BUYER_CONFIRMATION:
            order.whatsapp_workflow_state = "awaiting_cancellation_confirmation"
            if phone and cfg.twilio_cancellation_content_sid:
                outbound_message = (cfg.twilio_cancellation_content_sid, {"1": order.id})
        elif (
            action_id == "delivery_date_yes"
            and order.whatsapp_workflow_state == "awaiting_delivery_date_confirmation"
        ):
            order.status = OrderStatus.DELIVERY_SCHEDULED
            order.whatsapp_workflow_state = "delivery_scheduled"
            session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.DELIVERY_SCHEDULED, actor="buyer"))
        elif (
            action_id == "delivery_date_reschedule"
            and order.whatsapp_workflow_state == "awaiting_delivery_date_confirmation"
        ):
            order.whatsapp_workflow_state = "awaiting_reschedule_choice"
            if phone and cfg.twilio_reschedule_content_sid:
                proposed = order.promised_delivery_date.date()
                outbound_message = (
                    cfg.twilio_reschedule_content_sid,
                    {
                        "1": order.id,
                        "2": (proposed + timedelta(days=1)).isoformat(),
                        "3": (proposed + timedelta(days=2)).isoformat(),
                    },
                )
        elif (
            action_id in {"reschedule_plus_1", "reschedule_plus_2"}
            and order.whatsapp_workflow_state == "awaiting_reschedule_choice"
        ):
            days = 1 if action_id.endswith("1") else 2
            order.promised_delivery_date += timedelta(days=days)
            order.rescheduled_count += 1
            order.status = OrderStatus.DELIVERY_SCHEDULED
            order.whatsapp_workflow_state = "delivery_scheduled"
            session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.DELIVERY_SCHEDULED, actor="buyer"))
        elif action_id == "keep_order" and order.whatsapp_workflow_state == "awaiting_cancellation_confirmation":
            order.whatsapp_workflow_state = "awaiting_order_confirmation"
        elif action_id in {"cancel_order", "delivery_date_cancel", "reschedule_cancel"}:
            order.status = OrderStatus.CANCELLED
            order.whatsapp_workflow_state = "cancelled"
            session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.CANCELLED, actor="buyer"))
            if order.stock_decremented:
                items = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().all()
                for item in items:
                    variant = session.get(ProductVariant, item.product_variant_id)
                    if variant:
                        variant.stock_qty += item.qty
                order.stock_decremented = False
            payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalars().first()
            if payment and payment.status == "captured":
                payment.status = "refund_pending"
        else:
            raise HTTPException(status_code=409, detail="Stale or invalid WhatsApp action")

        try:
            # The buyer's decision is authoritative and must be durable before a
            # follow-up message is sent. A provider call can no longer roll it back.
            session.commit()
            if outbound_message and phone:
                sid = provider.send_whatsapp_content(phone, outbound_message[0], outbound_message[1])
                try:
                    from kavach_saathi.providers.twilio_integration import normalize_phone_number

                    redis = get_redis()
                    redis.setex(f"whatsapp:outbound:{sid}", 86400, order.id)
                    redis.setex(f"whatsapp:pending:{normalize_phone_number(phone)}", 86400, order.id)
                except Exception:
                    logger.warning("Could not store WhatsApp correlation for order %s", order.id, exc_info=True)
            try:
                get_redis().set(webhook_key, "complete", ex=604800)
            except Exception:
                pass
        except Exception:
            try:
                get_redis().delete(webhook_key)
            except Exception:
                pass
            raise
        return Response(content='<?xml version="1.0"?><Response/>', media_type="text/xml")

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
