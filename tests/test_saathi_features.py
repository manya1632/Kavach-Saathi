from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import Order, OrderItem, Product, ReturnRecord, User, OrderStatusHistory, Review
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.agents.confirmation import DeliveryConfirmationAgent
from kavach_saathi.repository import CommerceRepository

def cleanup_test_entities(session):
    session.rollback()
    # 0. Delete Reviews
    session.query(Review).filter(Review.product_id.in_(["P-TEST-456", "P-TEST-123"])).delete()
    session.commit()
    # 1. Delete ReturnRecords
    session.query(ReturnRecord).filter(ReturnRecord.id.in_(["RT-TEST-456", "RT-TEST-123"])).delete()
    session.commit()

    # 2. Delete replacement orders
    rep_orders = session.query(Order).filter(Order.original_order_id.in_(["O-TEST-456", "O-TEST-123"]), Order.exchange_tag == True).all()
    for ro in rep_orders:
        session.query(OrderItem).filter(OrderItem.order_id == ro.id).delete()
        session.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == ro.id).delete()
        session.query(Order).filter(Order.id == ro.id).delete()
    session.commit()

    # 3. Delete original orders
    for oid in ["O-TEST-456", "O-TEST-123"]:
        session.query(OrderItem).filter(OrderItem.order_id == oid).delete()
        session.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == oid).delete()
        session.query(Order).filter(Order.id == oid).delete()
    session.commit()

    # 4. Delete products and users
    session.query(Product).filter(Product.id.in_(["P-TEST-456", "P-TEST-123"])).delete()
    session.query(User).filter(User.id.in_(["B-TEST-456", "B-TEST-123"])).delete()
    session.commit()

def test_stock_decrement_standard_product():
    """Verify that standard products without variants have their stock decremented
    correctly when the order is transitioned to DELIVERED status.
    """
    session = SessionLocal()
    cleanup_test_entities(session)
    try:
        # 1. Create a dummy buyer and product
        buyer = User(
            id="B-TEST-123",
            role="buyer",
            name="Test Buyer",
            email="testbuyer@example.com",
            password_hash="no_hash"
        )
        product = Product(
            id="P-TEST-123",
            title="Test Standard Product",
            category="Saree",
            seller_id="S-001",
            price=999.0,
            original_price=999.0,
            stock=10,
            status="active"
        )
        session.add(buyer)
        session.add(product)
        session.flush()

        # 2. Create order and order items
        order = Order(
            id="O-TEST-123",
            buyer_id=buyer.id,
            status=OrderStatus.PLACED,
            total_amount=999.0,
            payment_mode="cod",
            stock_decremented=False
        )
        session.add(order)
        session.flush()

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_variant_id=None,  # Standard product with no variant
            seller_id="S-001",
            qty=2,
            price_at_purchase=999.0
        )
        session.add(order_item)
        session.commit()

        # 3. Trigger delivery transition
        agent = DeliveryConfirmationAgent(context=None)
        
        # We need a new session context to run transaction and lock
        test_session = SessionLocal()
        try:
            agent.execute_delivery_transition(test_session, "O-TEST-123", actor="test")
            test_session.commit()
        finally:
            test_session.close()

        # 4. Assert stock has been decremented
        session.expire_all()
        updated_product = session.get(Product, "P-TEST-123")
        updated_order = session.get(Order, "O-TEST-123")

        assert updated_product.stock == 8
        assert updated_order.stock_decremented is True
        assert updated_order.status == OrderStatus.DELIVERED

    finally:
        cleanup_test_entities(session)
        session.close()

def test_return_exchange_approval_and_replacement_order():
    """Verify that approving an exchange return request automatically schedules a pickup,
    creates a zero-cost replacement order with the EXCHANGE tag, and stores the status.
    """
    session = SessionLocal()
    cleanup_test_entities(session)
    try:
        # 1. Create entities
        buyer = User(
            id="B-TEST-456",
            role="buyer",
            name="Test Buyer 2",
            email="testbuyer2@example.com",
            password_hash="no_hash"
        )
        product = Product(
            id="P-TEST-456",
            title="Test Exchange Product",
            category="Kurti",
            seller_id="S-001",
            price=500.0,
            original_price=500.0,
            stock=5,
            status="active"
        )
        session.add(buyer)
        session.add(product)
        session.flush()

        order = Order(
            id="O-TEST-456",
            buyer_id=buyer.id,
            status=OrderStatus.DELIVERED,
            total_amount=500.0,
            payment_mode="cod"
        )
        session.add(order)
        session.flush()

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            seller_id="S-001",
            qty=1,
            price_at_purchase=500.0
        )
        session.add(order_item)
        session.flush()

        # Create return request
        return_rec = ReturnRecord(
            id="RT-TEST-456",
            order_id=order.id,
            buyer_id=buyer.id,
            reason="Size too small",
            return_type="exchange",
            status="pending_evidence"
        )
        session.add(return_rec)
        session.commit()

        # 2. Call record_return_decision with "approve"
        repo = CommerceRepository()
        repo.record_return_decision("O-TEST-456", buyer_id=buyer.id, video_key="video.mp4", confidence_score=85, decision="approve")

        # 3. Assert results
        session.expire_all()
        updated_return = session.get(ReturnRecord, "RT-TEST-456")
        assert updated_return.decision == "approve"
        assert updated_return.status == "pickup_scheduled"
        assert updated_return.pickup_date is not None
        assert updated_return.pickup_status == "scheduled"
        assert updated_return.replacement_order_id is not None

        # Verify replacement order
        rep_order_id = updated_return.replacement_order_id
        rep_order = session.get(Order, rep_order_id)
        assert rep_order is not None
        assert rep_order.exchange_tag is True
        assert rep_order.original_order_id == "O-TEST-456"
        assert rep_order.total_amount == 0.0
        assert rep_order.status == OrderStatus.CONFIRMED

        rep_item = session.query(OrderItem).filter(OrderItem.order_id == rep_order_id).first()
        assert rep_item is not None
        assert rep_item.product_id == "P-TEST-456"
        assert rep_item.price_at_purchase == 0.0

    finally:
        cleanup_test_entities(session)
        session.close()


def test_reviews_verification():
    """Verify that submitting a review triggers multimodal verification and updates database validation fields and aggregate product rating inside a transaction."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from kavach_saathi.commerce_api import create_review
    from kavach_saathi.models import ReviewCreateRequest
    from kavach_saathi.db.models import Review, Product
    from kavach_saathi.providers.review_provider import ReviewVerificationResult

    session = SessionLocal()
    cleanup_test_entities(session)
    try:
        # Create user, product, order
        buyer = User(
            id="B-TEST-123",
            role="buyer",
            name="Test Review Buyer",
            email="testreview@example.com",
            password_hash="no_hash"
        )
        product = Product(
            id="P-TEST-123",
            title="Test Saree",
            category="Saree",
            seller_id="S-001",
            price=1000.0,
            original_price=1000.0,
            stock=10,
            rating=4.0,
            review_count=1,
            media_primary="catalogue_primary.jpg",
            status="active"
        )
        order = Order(
            id="O-TEST-123",
            buyer_id=buyer.id,
            status=OrderStatus.DELIVERED,
            total_amount=1000.0,
            payment_mode="cod"
        )
        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            seller_id="S-001",
            qty=1,
            price_at_purchase=1000.0
        )
        session.add(buyer)
        session.add(product)
        session.flush()

        session.add(order)
        session.add(order_item)
        session.commit()

        payload = ReviewCreateRequest(
            product_id=product.id,
            order_id=order.id,
            rating=5,
            text="This is a very beautiful saree. Fabric is excellent.",
            image_key="review_photo.jpg"
        )

        mock_result = ReviewVerificationResult(
            product_image_match_passed=True,
            product_image_match_confidence=85,
            product_image_match_reason="Matches catalogue perfectly.",
            image_text_match_passed=True,
            image_text_match_confidence=90,
            image_text_match_reason="Review text matches saree picture.",
            text_quality_passed=True,
            text_quality_classification="relevant",
            text_quality_reason="Helpful fabric review.",
            overall_passed=True,
            provider="gemini",
            model="gemini-2.5-flash"
        )

        from kavach_saathi.container import Container
        from kavach_saathi.config import get_settings
        container = Container(get_settings())

        async def run_test():
            with patch("kavach_saathi.media_storage.read_image_bytes", AsyncMock(return_value=b"dummy_bytes")):
                with patch("kavach_saathi.providers.review_provider.ReviewVerificationProvider.verify", AsyncMock(return_value=mock_result)):
                    return await create_review(
                        payload=payload,
                        user=buyer,
                        session=session,
                        container=container
                    )

        res = asyncio.run(run_test())

        session.expire_all()
        review = session.get(Review, res["id"])
        assert review is not None
        assert review.validation_provider == "gemini"
        assert review.product_image_match_confidence == 85
        assert review.text_quality_classification == "relevant"
        assert review.overall_passed is True

        updated_product = session.get(Product, product.id)
        assert updated_product.review_count == 2
        assert updated_product.rating == 4.5  # (4.0 * 1 + 5) / 2 = 4.5

    finally:
        cleanup_test_entities(session)
        session.close()


def test_return_verification_multimodal():
    """Verify that return evidence submissions execute ReturnComparisonProvider and log results properly in database."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from kavach_saathi.commerce_api import submit_return_image_attempt
    from kavach_saathi.models import ReturnImageAttemptRequest
    from kavach_saathi.db.models import ReturnRecord
    from kavach_saathi.providers.return_provider import ReturnComparisonResult

    session = SessionLocal()
    cleanup_test_entities(session)
    try:
        buyer = User(
            id="B-TEST-456",
            role="buyer",
            name="Test Return Buyer",
            email="testreturn@example.com",
            password_hash="no_hash"
        )
        product = Product(
            id="P-TEST-456",
            title="Test Saree",
            category="Saree",
            seller_id="S-001",
            price=1000.0,
            original_price=1000.0,
            stock=10,
            status="active"
        )
        order = Order(
            id="O-TEST-456",
            buyer_id=buyer.id,
            status=OrderStatus.DELIVERED,
            total_amount=1000.0,
            payment_mode="cod"
        )
        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            seller_id="S-001",
            qty=1,
            price_at_purchase=1000.0,
            delivery_front_image="del_front.jpg",
            delivery_back_image="del_back.jpg"
        )
        return_rec = ReturnRecord(
            id="RT-TEST-456",
            order_id=order.id,
            product_id=product.id,
            buyer_id=buyer.id,
            reason="Color mismatch",
            status="pending_evidence"
        )
        session.add(buyer)
        session.add(product)
        session.flush()

        session.add(order)
        session.add(order_item)
        session.add(return_rec)
        session.commit()

        import uuid
        payload = ReturnImageAttemptRequest(
            front_image_key="buyer_front.jpg",
            back_image_key="buyer_back.jpg",
            idempotency_key=f"idempotency_key_{uuid.uuid4().hex[:10]}"
        )

        mock_front = ReturnComparisonResult(
            visual_similarity_score=80,
            mismatch_detected=False,
            visible_differences=[],
            comparison_type="front",
            provider="gemini",
            model="gemini-2.5-flash"
        )
        mock_back = ReturnComparisonResult(
            visual_similarity_score=70,
            mismatch_detected=False,
            visible_differences=[],
            comparison_type="back",
            provider="gemini",
            model="gemini-2.5-flash"
        )

        async def run_test():
            from kavach_saathi.config import get_settings
            with patch("kavach_saathi.commerce_api._read_valid_return_image", AsyncMock(return_value=b"dummy_image")):
                with patch("kavach_saathi.providers.return_provider.ReturnComparisonProvider.compare") as mock_compare:
                    mock_compare.side_effect = [mock_front, mock_back]
                    return await submit_return_image_attempt(
                        return_id=return_rec.id,
                        payload=payload,
                        user=buyer,
                        cfg=get_settings(),
                        session=session
                    )

        res = asyncio.run(run_test())

        session.expire_all()
        updated_rec = session.get(ReturnRecord, return_rec.id)
        assert updated_rec.status == "pending_return"
        assert updated_rec.decision == "evidence_matched"
        assert len(updated_rec.attempt_history) == 1
        attempt = updated_rec.attempt_history[0]
        assert attempt["similarity_front"] == 80
        assert attempt["similarity_back"] == 70
        assert attempt["similarity_aggregate"] == 75.0
        assert attempt["front_provider"] == "gemini"

    finally:
        cleanup_test_entities(session)
        session.close()
