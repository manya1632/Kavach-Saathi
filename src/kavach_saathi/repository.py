from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import (
    Address,
    Order,
    OrderItem,
    OtpSession,
    Product,
    ProductImage,
    ProductSpecification,
    ReturnRecord,
    Review,
    SellerProfile,
    User,
)


class DataNotFoundError(KeyError):
    pass


def _seller_dict(profile: SellerProfile) -> dict[str, Any]:
    return {
        "id": profile.user_id,
        "name": profile.business_name,
        "city": profile.city,
        "rating": profile.rating,
        "on_time_rate": profile.on_time_rate,
        "return_rate": profile.return_rate,
        "verified": profile.verified,
        "digilocker_kyc_status": profile.digilocker_kyc_status,
        "trust_score": profile.trust_score,
        "gstin": profile.gstin,
    }


def _buyer_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "city": user.city,
        "phone": user.phone,
        "language": user.preferred_language,
        "measurements_cm": user.measurements_cm,
        "trusted_returner": user.trusted_returner,
    }


_SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "XXXL"]


def _ordered_size_chart(size_chart: dict[str, Any]) -> dict[str, Any]:
    """Postgres's JSONB column type does not preserve key insertion order on read
    (unlike JSON) -- a chart written as XS/S/M/L/XL/XXL can come back in a different
    order every time, which showed up live as size buttons rendering L, M, S, XL...
    instead of small-to-large. Re-sorting here by a fixed canonical order, rather than
    trusting dict iteration order end to end, fixes it regardless of what JSONB
    happens to return."""
    return {
        size: size_chart[size]
        for size in sorted(size_chart, key=lambda s: _SIZE_ORDER.index(s) if s in _SIZE_ORDER else len(_SIZE_ORDER))
    }


def _product_dict(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.title,
        "brand": product.brand,
        "seller_id": product.seller_id,
        "category": product.category,
        "audience": product.audience,
        "description": product.description,
        "price": product.price,
        "original_price": product.original_price,
        "status": product.status,
        "rating": product.rating,
        "review_count": product.review_count,
        "stock": product.stock,
        "delivery_days": product.delivery_days,
        "free_delivery": product.free_delivery,
        "cod_available": product.cod_available,
        "occasion": product.occasion,
        "material": product.material,
        "highlights": product.highlights,
        "badges": product.badges,
        "presentation": product.presentation,
        "specs": product.spec_json,
        "label_backed_fields": product.label_backed_fields,
        "spec_source": product.spec_source,
        "stolen_photo_flag": product.stolen_photo_flag,
        "size_chart": _ordered_size_chart(product.size_chart),
        "return_window_days": product.return_window_days,
        "media": {"primary": product.media_primary, "care_label": product.media_care_label},
        "product_images": product.product_images,
        "catalogue_images": product.catalogue_images,
        "extraction_results": product.extraction_results,
        "seller_corrections": product.seller_corrections,
        "activation_timestamp": product.activation_timestamp.isoformat() if product.activation_timestamp else None,
    }


def _normalized_spec(row: ProductSpecification) -> dict[str, Any]:
    aliases = {
        "garment_length": "length",
        "product_length": "length",
        "length_cm": "length",
        "chest_cm": "chest",
        "bust": "chest",
        "waist_cm": "waist",
        "fabric_composition": "fabric",
        "material_composition": "fabric",
    }
    normalized_key = aliases.get(row.key, row.key.removesuffix("_cm"))
    value, unit = row.value_json, row.unit
    if isinstance(value, (int, float)) and unit:
        unit_key = unit.casefold()
        if unit_key == "mm":
            value, unit = value / 10, "cm"
        elif unit_key in {"m", "meter", "metre"}:
            value, unit = value * 100, "cm"
        elif unit_key in {"in", "inch", "inches"}:
            value, unit = round(value * 2.54, 2), "cm"
    return {
        "key": row.key,
        "normalized_key": normalized_key,
        "label": row.label,
        "value": row.value_json,
        "normalized_value": value,
        "value_type": row.value_type,
        "unit": row.unit,
        "normalized_unit": unit,
        "comparison_group": row.comparison_group,
        "comparable": row.comparable,
        "source": row.source,
        "verified": row.verified,
    }


def _order_dict(order: Order, item: OrderItem | None) -> dict[str, Any]:
    return {
        "id": order.id,
        "buyer_id": order.buyer_id,
        "product_id": item.product_id if item else None,
        "seller_id": item.seller_id if item else None,
        "size": item.size if item else None,
        "status": order.status,
        "fit_feedback": order.fit_feedback,
        "return_outcome": order.return_outcome,
        "order_value": order.total_amount,
        "payment_mode": order.payment_mode,
        "address_id": order.address_id,
    }


_REVIEWER_FIRST_NAMES = [
    "Rohit", "Priya", "Aman", "Sneha", "Vikram", "Anjali", "Rahul", "Divya", "Karan", "Pooja",
    "Nikhil", "Shreya", "Arjun", "Neha", "Suresh", "Kavita", "Manish", "Ritu", "Deepak", "Swati",
    "Ajay", "Preeti", "Sanjay", "Meena", "Vivek", "Anita", "Rakesh", "Sunita", "Gaurav", "Nisha",
    "Harish", "Komal", "Sandeep", "Priyanka", "Ashok", "Rekha", "Naveen", "Simran", "Yogesh", "Alka",
]
_REVIEWER_LAST_INITIALS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _reviewer_display_name(review_id: str) -> str:
    """Deterministic per-review display name (e.g. "Rohit K.") derived from the
    review's own id -- avoids a schema migration and avoids showing a raw buyer_id
    (e.g. "B-003") as the reviewer, which would look nothing like a real storefront
    and would also make the same 10 seeded buyer accounts visibly repeat across
    thousands of reviews. Uses sha1, not the builtin hash(), since str hashing is
    randomized per-process in Python -- hash() here would reshuffle every name on
    every backend restart."""
    digest = int(hashlib.sha1(review_id.encode()).hexdigest(), 16)
    first = _REVIEWER_FIRST_NAMES[digest % len(_REVIEWER_FIRST_NAMES)]
    last = _REVIEWER_LAST_INITIALS[(digest // len(_REVIEWER_FIRST_NAMES)) % len(_REVIEWER_LAST_INITIALS)]
    return f"{first} {last}."


def _review_dict(review: Review) -> dict[str, Any]:
    return {
        "id": review.id,
        "buyer_id": review.buyer_id,
        "product_id": review.product_id,
        "rating": review.rating,
        "text": review.text,
        "media": review.media,
        "is_hidden_by_agent": review.is_hidden_by_agent,
        "hide_reason": review.hide_reason,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "reviewer_name": _reviewer_display_name(review.id),
    }


def _address_dict(address: Address) -> dict[str, Any]:
    return {
        "id": address.id,
        "buyer_id": address.user_id,
        "raw_address": address.raw_text,
        "city": address.city,
        "state": address.state,
        "postal_pin": address.postal_pin,
        "coordinates": {"latitude": address.latitude, "longitude": address.longitude},
        "digipin": address.digipin,
        "verified": address.verified_bool,
        "is_default": address.is_default,
    }


def _return_dict(record: ReturnRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "order_id": record.order_id,
        "buyer_id": record.buyer_id,
        "video": record.video_url,
        "confidence_score": record.confidence_score,
        "decision": record.decision,
    }


class CommerceRepository:
    """Postgres-backed repository — the single source of truth for both demo and live
    modes. Replaces the old JSON-fixture repository and the DynamoDB adapter; there is
    now exactly one storage implementation, per the plan's "no fake demo/live split" rule.
    """

    COLLECTIONS = ("products", "sellers", "buyers", "orders", "reviews", "addresses", "returns")

    def __init__(self, session_factory: Any = SessionLocal):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def get(self, collection: str, record_id: str) -> dict[str, Any]:
        with self._session() as session:
            if collection == "products":
                product = session.get(Product, record_id)
                if not product:
                    raise DataNotFoundError(f"products:{record_id} not found")
                return _product_dict(product)
            if collection == "sellers":
                profile = session.get(SellerProfile, record_id)
                if not profile:
                    raise DataNotFoundError(f"sellers:{record_id} not found")
                return _seller_dict(profile)
            if collection == "buyers":
                user = session.get(User, record_id)
                if not user or user.role != "buyer":
                    raise DataNotFoundError(f"buyers:{record_id} not found")
                return _buyer_dict(user)
            if collection == "orders":
                order = session.get(Order, record_id)
                if not order:
                    raise DataNotFoundError(f"orders:{record_id} not found")
                item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().first()
                return _order_dict(order, item)
            if collection == "reviews":
                review = session.get(Review, record_id)
                if not review:
                    raise DataNotFoundError(f"reviews:{record_id} not found")
                return _review_dict(review)
            if collection == "addresses":
                address = session.get(Address, record_id)
                if not address:
                    raise DataNotFoundError(f"addresses:{record_id} not found")
                return _address_dict(address)
            if collection == "returns":
                record = session.get(ReturnRecord, record_id)
                if not record:
                    raise DataNotFoundError(f"returns:{record_id} not found")
                return _return_dict(record)
            raise DataNotFoundError(f"Unknown collection: {collection}")

    def list(self, collection: str) -> list[dict[str, Any]]:
        with self._session() as session:
            if collection == "products":
                rows = session.execute(select(Product).order_by(Product.id)).scalars()
                return [_product_dict(p) for p in rows]
            if collection == "sellers":
                rows = session.execute(select(SellerProfile).order_by(SellerProfile.user_id)).scalars()
                return [_seller_dict(p) for p in rows]
            if collection == "buyers":
                users = session.execute(select(User).where(User.role == "buyer").order_by(User.id)).scalars()
                return [_buyer_dict(u) for u in users]
            if collection == "orders":
                items_by_order: dict[str, OrderItem] = {}
                for item in session.execute(select(OrderItem)).scalars():
                    items_by_order.setdefault(item.order_id, item)
                orders = session.execute(select(Order).order_by(Order.id)).scalars()
                return [_order_dict(order, items_by_order.get(order.id)) for order in orders]
            if collection == "reviews":
                rows = session.execute(select(Review).order_by(Review.id)).scalars()
                return [_review_dict(r) for r in rows]
            if collection == "addresses":
                rows = session.execute(select(Address).order_by(Address.id)).scalars()
                return [_address_dict(a) for a in rows]
            if collection == "returns":
                rows = session.execute(select(ReturnRecord).order_by(ReturnRecord.id)).scalars()
                return [_return_dict(r) for r in rows]
            return []

    def buyer_orders(self, buyer_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            orders = session.execute(select(Order).where(Order.buyer_id == buyer_id)).scalars().all()
            items_by_order: dict[str, OrderItem] = {}
            if orders:
                order_ids = [o.id for o in orders]
                for item in session.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).scalars():
                    items_by_order.setdefault(item.order_id, item)
            return [_order_dict(order, items_by_order.get(order.id)) for order in orders]

    def products_in_category(self, category: str, *, exclude_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.execute(
                select(Product)
                .where(Product.category == category, Product.id != exclude_id, Product.size_chart != {})
                .order_by(Product.id)
                .limit(limit)
            ).scalars()
            return [_product_dict(p) for p in rows]

    def product_reviews(self, product_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            reviews = session.execute(
                select(Review).where(Review.product_id == product_id).order_by(Review.created_at.desc())
            ).scalars()
            return [_review_dict(r) for r in reviews]

    def review_report(self, product_id: str) -> dict[str, Any]:
        """Aggregate counts backing the storefront's review-truth report -- computed
        live from Review.is_hidden_by_agent rather than a separately stored summary,
        since that column already holds Agent 4's real per-review CLIP+BERT verdict
        (see scripts/classify_seeded_reviews.py) and a per-product review count in the
        low tens is cheap enough to aggregate on every request."""
        with self._session() as session:
            from sqlalchemy import func

            total, with_media, flagged = session.execute(
                select(
                    func.count(Review.id),
                    func.count(Review.id).filter(Review.media.is_not(None)),
                    func.count(Review.id).filter(Review.is_hidden_by_agent.is_(True)),
                ).where(Review.product_id == product_id)
            ).one()
            return {
                "total_reviews": total,
                "photos_submitted": with_media,
                "photos_verified": with_media - flagged,
                "photos_flagged": flagged,
            }

    def product_specifications(self, product_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.execute(
                select(ProductSpecification)
                .where(ProductSpecification.product_id == product_id)
                .order_by(ProductSpecification.comparison_group, ProductSpecification.label)
            ).scalars()
            return [_normalized_spec(row) for row in rows]

    def product_images(self, product_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            product = session.get(Product, product_id)
            rows = session.execute(
                select(ProductImage)
                .where(
                    ProductImage.product_id == product_id,
                    ProductImage.angle.in_(("front", "back", "left", "right")),
                )
                .order_by(ProductImage.is_verified.desc(), ProductImage.created_at.desc())
            ).scalars()
            by_angle: dict[str, dict[str, Any]] = {}
            for row in rows:
                # Until Agent 1 has produced a verified angle, persistently use the
                # seller's real primary upload for each labelled slot.
                url = row.url if row.is_verified else (product.media_primary if product else row.url)
                by_angle.setdefault(row.angle, {"angle": row.angle, "url": url, "verified": row.is_verified})
            return [by_angle[angle] for angle in ("front", "back", "left", "right") if angle in by_angle]

    def comparison_products(self, question: str, primary_id: str, explicit_ids: list[str]) -> list[dict[str, Any]]:
        query = question.casefold()
        with self._session() as session:
            active = (
                session.execute(select(Product).where(Product.status == "active").order_by(Product.id)).scalars().all()
            )
            primary = session.get(Product, primary_id)
            selected: list[Product] = [primary] if primary else []
            by_id = {product.id: product for product in active}
            for product_id in explicit_ids:
                product = by_id.get(product_id) or session.get(Product, product_id)
                if product and product not in selected:
                    selected.append(product)
            aliases = {
                "kurta": "Kurti, Saree & Lehenga",
                "kurti": "Kurti, Saree & Lehenga",
                "saree": "Kurti, Saree & Lehenga",
                "lehenga": "Kurti, Saree & Lehenga",
                "men": "Men",
                "kids": "Kids & Toys",
                "beauty": "Beauty & Health",
                "jewellery": "Jewellery & Accessories",
                "jewelry": "Jewellery & Accessories",
                "bags": "Bags & Footwear",
                "footwear": "Bags & Footwear",
                "home": "Home & Kitchen",
                "western": "Women Western",
            }
            category = next((value for key, value in aliases.items() if key in query), None)
            wants_all = any(token in query for token in ("all ", "sab ", "saare ", "every "))
            if category and wants_all:
                selected = [product for product in active if product.category == category]
            else:
                for product in active:
                    if (
                        product.id.casefold() in query
                        or product.title.casefold() in query
                        or (product.brand and product.brand.casefold() in query)
                    ) and product not in selected:
                        selected.append(product)
            output = []
            for product in selected:
                item = _product_dict(product)
                rows = session.execute(
                    select(ProductSpecification).where(ProductSpecification.product_id == product.id)
                ).scalars()
                item["specifications"] = [_normalized_spec(row) for row in rows]
                output.append(item)
            return output

    def return_for_order(self, order_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            record = session.execute(select(ReturnRecord).where(ReturnRecord.order_id == order_id)).scalars().first()
            return _return_dict(record) if record else None

    def summary(self) -> dict[str, int]:
        with self._session() as session:
            from sqlalchemy import func

            counts = {}
            counts["products"] = session.scalar(select(func.count()).select_from(Product)) or 0
            counts["sellers"] = session.scalar(select(func.count()).select_from(SellerProfile)) or 0
            counts["buyers"] = session.scalar(select(func.count()).select_from(User).where(User.role == "buyer")) or 0
            counts["orders"] = session.scalar(select(func.count()).select_from(Order)) or 0
            counts["reviews"] = session.scalar(select(func.count()).select_from(Review)) or 0
            counts["addresses"] = session.scalar(select(func.count()).select_from(Address)) or 0
            counts["returns"] = session.scalar(select(func.count()).select_from(ReturnRecord)) or 0
            return counts

    def save_generated_images(self, product_id: str, images: list[dict[str, Any]]) -> None:
        """Persist Agent 1's generated 4-shot set as real `product_images` rows,
        recording which provider (Nano Banana 2 vs Stable Diffusion fallback) served
        each angle."""
        with self._session() as session:
            for image in images:
                image_id = f"{product_id}-{image['view']}"
                existing = session.get(ProductImage, image_id)
                if existing:
                    existing.url = image["key"]
                    existing.provider = image["provider"]
                    existing.is_verified = True
                else:
                    session.add(
                        ProductImage(
                            id=image_id,
                            product_id=product_id,
                            url=image["key"],
                            type="ai_generated",
                            angle=image["view"],
                            is_verified=True,
                            provider=image["provider"],
                        )
                    )
            session.commit()

    def set_stolen_photo_flag(self, product_id: str, flagged: bool) -> None:
        with self._session() as session:
            product = session.get(Product, product_id)
            if product:
                product.stolen_photo_flag = flagged
                session.commit()

    def update_order_status(self, order_id: str, status: str, *, actor: str = "agent") -> None:
        from kavach_saathi.db.models import OrderStatusHistory

        with self._session() as session:
            order = session.get(Order, order_id)
            if not order:
                return
            order.status = status
            session.add(OrderStatusHistory(order_id=order_id, status=status, actor=actor))
            session.commit()

    def save_verified_address(
        self,
        buyer_id: str,
        *,
        raw_address: str,
        city: str | None,
        state: str | None,
        postal_pin: str | None,
        latitude: float,
        longitude: float,
        digipin: str | None,
        recipient_name: str | None = None,
        phone: str | None = None,
        address_line1: str | None = None,
        address_line2: str | None = None,
        locality: str | None = None,
        district: str | None = None,
        country: str | None = "India",
        address_type: str | None = "Home",
        phone_verified: bool = False,
        validation_status: str = "valid",
        validation_explanation: str | None = None,
        is_default: bool = True,
    ) -> str:
        """Persist verified address as a real `addresses` row (final target
        plan.md commerce backbone) -- supporting structured address data, geocoding
        metadata, validation status and custom default/non-default flags.
        """
        import uuid

        with self._session() as session:
            if is_default:
                session.execute(update(Address).where(Address.user_id == buyer_id).values(is_default=False))
            address_id = f"A-{uuid.uuid4().hex[:10].upper()}"
            session.add(
                Address(
                    id=address_id,
                    user_id=buyer_id,
                    raw_text=raw_address,
                    city=city,
                    state=state,
                    postal_pin=postal_pin,
                    latitude=latitude,
                    longitude=longitude,
                    digipin=digipin,
                    verified_bool=True,
                    is_default=is_default,
                    recipient_name=recipient_name or buyer_id,
                    phone=phone,
                    address_line1=address_line1 or raw_address,
                    address_line2=address_line2,
                    locality=locality,
                    district=district or city,
                    country=country or "India",
                    address_type=address_type or "Home",
                    phone_verified=phone_verified,
                    validation_status=validation_status,
                    validation_explanation=validation_explanation,
                )
            )
            session.commit()
            return address_id

    def set_review_hidden(self, review_id: str, *, hidden: bool, reason: str | None) -> None:
        with self._session() as session:
            review = session.get(Review, review_id)
            if review:
                review.is_hidden_by_agent = hidden
                review.hide_reason = reason
                session.commit()

    def record_return_decision(
        self,
        order_id: str,
        *,
        buyer_id: str | None,
        video_key: str,
        confidence_score: int,
        decision: str,
    ) -> str:
        """Persist Agent 8's decision as a real `returns` row and stamp the parent
        order's `return_outcome` -- previously computed and returned to the caller but
        never written anywhere, leaving `seller_trust_score`/`buyer_trust_signals`
        with no real return data to compute from.
        """
        import uuid
        from datetime import UTC, datetime, timedelta
        from kavach_saathi.order_status import OrderStatus
        from kavach_saathi.db.models import OrderStatusHistory, OrderItem

        with self._session() as session:
            record = session.execute(select(ReturnRecord).where(ReturnRecord.order_id == order_id)).scalars().first()
            if record is None:
                record = ReturnRecord(id=f"RT-{uuid.uuid4().hex[:10].upper()}", order_id=order_id)
                session.add(record)
            record.buyer_id = buyer_id
            record.video_url = video_key
            record.confidence_score = confidence_score
            
            order = session.get(Order, order_id)
            
            # Use finalize_return_record_decision logic
            record.decision = decision
            record.decided_at = datetime.now(UTC)

            if order:
                order.return_outcome = decision

            if decision == "approve":
                record.status = "pickup_scheduled"
                if order:
                    order.status = OrderStatus.RETURN_APPROVED
                    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_APPROVED, actor="system"))
                
                record.pickup_date = datetime.now(UTC) + timedelta(days=3)
                record.pickup_status = "scheduled"

                if record.return_type == "exchange":
                    if not record.replacement_order_id:
                        replacement_id = f"O-EXCH-{uuid.uuid4().hex[:10].upper()}"
                        orig_items = session.query(OrderItem).filter(OrderItem.order_id == record.order_id).all()
                        replacement_order = Order(
                            id=replacement_id,
                            buyer_id=record.buyer_id,
                            address_id=order.address_id if order else None,
                            status=OrderStatus.CONFIRMED,
                            total_amount=0.0,
                            payment_mode=order.payment_mode if order else "cod",
                            exchange_tag=True,
                            original_order_id=record.order_id,
                            stock_decremented=False,
                        )
                        session.add(replacement_order)
                        session.flush()

                        for orig_item in orig_items:
                            rep_item = OrderItem(
                                order_id=replacement_id,
                                product_id=orig_item.product_id,
                                product_variant_id=orig_item.product_variant_id,
                                seller_id=orig_item.seller_id,
                                size=orig_item.size,
                                qty=orig_item.qty,
                                price_at_purchase=0.0,
                            )
                            session.add(rep_item)
                        
                        record.replacement_order_id = replacement_id
                        session.add(OrderStatusHistory(order_id=replacement_id, status=OrderStatus.PLACED, actor="system"))
                        session.add(OrderStatusHistory(order_id=replacement_id, status=OrderStatus.CONFIRMED, actor="system"))
                        session.flush()

                elif record.return_type == "refund":
                    record.refund_status = "processing"
                    if order and order.payment_mode == "prepaid":
                        record.refund_masked_details = "Original Payment Method (Razorpay)"
                    else:
                        record.refund_masked_details = "Bank A/C: ******5678 (SBI)"

            elif decision == "manual_inspection":
                record.status = "manual_inspection"
                if order:
                    order.status = OrderStatus.MANUAL_INSPECTION
                    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.MANUAL_INSPECTION, actor="system"))
                    
            elif decision == "reject":
                record.status = "rejected"
                if order:
                    order.status = OrderStatus.RETURN_REJECTED
                    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_REJECTED, actor="system"))

            elif decision == "request_more_evidence":
                record.status = "needs_evidence"
                if order:
                    order.status = OrderStatus.RETURN_UNDER_REVIEW
                    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_UNDER_REVIEW, actor="system"))

            timeline = list(record.status_timeline or [])
            timeline.append({
                "status": record.status,
                "timestamp": datetime.now(UTC).isoformat(),
                "notes": f"Decision: {decision}"
            })
            record.status_timeline = timeline
            
            session.commit()
            return record.id

    def update_product_specs(
        self,
        product_id: str,
        *,
        spec_json: dict[str, Any] | None = None,
        spec_source: str | None = None,
        status: str | None = None,
    ) -> None:
        with self._session() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            if spec_json is not None:
                product.spec_json = {**product.spec_json, **spec_json}
                for key, value in spec_json.items():
                    record = (
                        session.execute(
                            select(ProductSpecification).where(
                                ProductSpecification.product_id == product_id,
                                ProductSpecification.key == key,
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if record is None:
                        record = ProductSpecification(
                            product_id=product_id,
                            key=key,
                            label=key.replace("_", " ").title(),
                            value_json=value,
                            value_type="number" if isinstance(value, (int, float)) else "text",
                            unit="GSM" if key == "gsm" else ("cm" if key.endswith("_cm") else None),
                            comparison_group="fabric"
                            if key in {"fabric", "gsm"}
                            else ("color" if "color" in key else "general"),
                            comparable=True,
                        )
                        session.add(record)
                    record.value_json = value
                    record.source = spec_source or "agent_cross_check"
                    record.verified = True
            if spec_source is not None:
                product.spec_source = spec_source
            if status is not None:
                product.status = status
            session.commit()

    def get_user_addresses(self, user_id: str) -> list[Address]:
        with self._session() as session:
            return (
                session.execute(select(Address).where(Address.user_id == user_id).order_by(Address.created_at.desc()))
                .scalars()
                .all()
            )

    def get_address(self, address_id: str) -> Address | None:
        with self._session() as session:
            return session.get(Address, address_id)

    def delete_address(self, address_id: str) -> bool:
        with self._session() as session:
            address = session.get(Address, address_id)
            if not address:
                return False
            # Check if used by an order
            orders_count = session.execute(select(Order).where(Order.address_id == address_id)).scalars().all()
            if orders_count:
                raise ValueError("Cannot delete address that is linked to an order")
            session.delete(address)
            session.commit()
            return True

    def set_default_address(self, user_id: str, address_id: str) -> None:
        with self._session() as session:
            session.execute(update(Address).where(Address.user_id == user_id).values(is_default=False))
            address = session.get(Address, address_id)
            if address and address.user_id == user_id:
                address.is_default = True
            session.commit()

    def create_otp_session(
        self, user_id: str, phone: str, address_session_id: str, otp_hash: str, expires_at: datetime
    ) -> OtpSession:
        import uuid

        with self._session() as session:
            session.execute(
                update(OtpSession)
                .where(
                    OtpSession.user_id == user_id,
                    OtpSession.phone == phone,
                    OtpSession.address_session_id == address_session_id,
                )
                .values(verified=False)
            )
            otp_id = f"OTP-{uuid.uuid4().hex[:10].upper()}"
            record = OtpSession(
                id=otp_id,
                user_id=user_id,
                phone=phone,
                address_session_id=address_session_id,
                otp_hash=otp_hash,
                expires_at=expires_at,
                attempts=0,
                verified=False,
            )
            session.add(record)
            session.commit()
            return record

    def get_active_otp_session(self, user_id: str, phone: str, address_session_id: str) -> OtpSession | None:
        with self._session() as session:
            return (
                session.execute(
                    select(OtpSession)
                    .where(
                        OtpSession.user_id == user_id,
                        OtpSession.phone == phone,
                        OtpSession.address_session_id == address_session_id,
                        OtpSession.verified.is_(False),
                    )
                    .order_by(OtpSession.created_at.desc())
                )
                .scalars()
                .first()
            )

    def get_verified_phone_session(self, user_id: str, phone: str, verification_session_id: str) -> OtpSession | None:
        with self._session() as session:
            return (
                session.execute(
                    select(OtpSession).where(
                        OtpSession.user_id == user_id,
                        OtpSession.phone == phone,
                        OtpSession.id == verification_session_id,
                        OtpSession.verified.is_(True),
                        OtpSession.expires_at > datetime.now(UTC),
                    )
                )
                .scalars()
                .first()
            )

    def increment_otp_attempts(self, session_id: str) -> int:
        with self._session() as session:
            record = session.get(OtpSession, session_id)
            if record:
                record.attempts += 1
                session.commit()
                return record.attempts
            return 0

    def mark_otp_verified(self, session_id: str) -> None:
        from datetime import UTC, datetime

        with self._session() as session:
            record = session.get(OtpSession, session_id)
            if record:
                record.verified = True
                record.verified_at = datetime.now(UTC)
                session.commit()
