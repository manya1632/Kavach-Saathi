from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import Order, OrderItem, Product, ReturnRecord, User, OrderStatusHistory
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.agents.confirmation import DeliveryConfirmationAgent
from kavach_saathi.repository import CommerceRepository

def cleanup_test_entities(session):
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
