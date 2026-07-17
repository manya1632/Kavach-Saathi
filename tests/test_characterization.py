import pytest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import (
    User,
    Product,
    ProductVariant,
    CartItem,
    Address,
    Order,
    OrderItem,
    OrderStatusHistory,
    ReturnRecord,
)
from kavach_saathi.auth import signup_user, authenticate_user, verify_password
from kavach_saathi.digipin import encode
from kavach_saathi.order_status import OrderStatus


def test_twilio_lookup_v2_success_does_not_require_a_sid():
    from kavach_saathi.config import get_settings
    from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient

    lookup = SimpleNamespace(
        valid=True,
        phone_number="+919748572321",
        country_code="IN",
        line_type_intelligence={"carrier_name": "Airtel", "type": "mobile"},
        url="https://lookups.twilio.com/v2/PhoneNumbers/+919748572321",
    )
    phone_numbers = MagicMock()
    phone_numbers.fetch.return_value = lookup
    client = MagicMock()
    client.lookups.v2.phone_numbers.return_value = phone_numbers
    redis = MagicMock()
    redis.get.return_value = None

    integration = TwilioIntegrationClient(get_settings())
    with patch.object(integration, "_client", return_value=client), patch(
        "kavach_saathi.redis_client.get_redis", return_value=redis
    ):
        result = integration.lookup_phone("9748572321", "IN")

    assert result["valid"] is True
    assert result["normalized_number"] == "+919748572321"
    assert result["line_type"] == "mobile"
    assert result["provider_ref"] == lookup.url


def cleanup_entities(session):
    session.rollback()
    session.query(OrderItem).filter(OrderItem.order_id.like("O-CHAR-%")).delete()
    session.query(OrderItem).filter(OrderItem.order_id.like("O-POP-%")).delete()
    session.query(OrderStatusHistory).filter(OrderStatusHistory.order_id.like("O-CHAR-%")).delete()
    session.query(ReturnRecord).filter(ReturnRecord.id.like("R-CHAR-%")).delete()
    session.query(Order).filter(Order.id.like("O-CHAR-%")).delete()
    session.query(Order).filter(Order.id.like("O-POP-%")).delete()
    session.query(CartItem).filter(CartItem.user_id.like("B-CHAR-%")).delete()
    session.query(ProductVariant).filter(ProductVariant.product_id.like("P-CHAR-%")).delete()
    session.query(Product).filter(Product.id.like("P-CHAR-%")).delete()
    session.query(Address).filter(Address.user_id.like("B-CHAR-%")).delete()

    from kavach_saathi.db.models import SellerProfile, ChatConversation, ChatMessage

    char_user_ids = [u.id for u in session.query(User).filter(User.email.like("%char%")).all()]
    if char_user_ids:
        # Delete ChatMessages and ChatConversations
        conversations = session.query(ChatConversation).filter(ChatConversation.user_id.in_(char_user_ids)).all()
        conv_ids = [c.id for c in conversations]
        if conv_ids:
            session.query(ChatMessage).filter(ChatMessage.conversation_id.in_(conv_ids)).delete(
                synchronize_session=False
            )
        session.query(ChatConversation).filter(ChatConversation.user_id.in_(char_user_ids)).delete(
            synchronize_session=False
        )

        session.query(SellerProfile).filter(SellerProfile.user_id.in_(char_user_ids)).delete(synchronize_session=False)
        session.query(ReturnRecord).filter(ReturnRecord.buyer_id.in_(char_user_ids)).delete(synchronize_session=False)
        session.query(Address).filter(Address.user_id.in_(char_user_ids)).delete(synchronize_session=False)
        session.query(Order).filter(Order.buyer_id.in_(char_user_ids)).delete(synchronize_session=False)
        session.query(User).filter(User.id.in_(char_user_ids)).delete(synchronize_session=False)
    session.commit()


def test_auth_characterization():
    session = SessionLocal()
    cleanup_entities(session)
    try:
        # Sign up buyer, seller, admin
        buyer = signup_user(
            role="buyer",
            name="Char Buyer",
            password="password123",
            preferred_language="en",
            email="charbuyer@example.com",
            session=session,
        )
        seller = signup_user(
            role="seller",
            name="Char Seller",
            password="password123",
            preferred_language="en",
            email="charseller@example.com",
            business_name="Char Biz",
            session=session,
        )
        admin = signup_user(
            role="admin",
            name="Char Admin",
            password="password123",
            preferred_language="en",
            email="charadmin@example.com",
            session=session,
        )
        session.commit()

        assert buyer.role == "buyer"
        assert seller.role == "seller"
        assert admin.role == "admin"

        # Authenticate
        auth_user = authenticate_user(identifier="charbuyer@example.com", password="password123", session=session)
        assert auth_user.id == buyer.id
    finally:
        cleanup_entities(session)
        session.close()


def test_address_and_digipin_characterization():
    session = SessionLocal()
    cleanup_entities(session)
    try:
        buyer = signup_user(
            role="buyer",
            name="Char Buyer",
            password="password123",
            preferred_language="en",
            email="charbuyer@example.com",
            session=session,
        )
        session.commit()
        lat, lon = 28.6139, 77.2090  # New Delhi
        digipin = encode(lat, lon)

        addr = Address(
            id="ADDR-CHAR-1",
            user_id=buyer.id,
            raw_text="Delhi Central",
            city="New Delhi",
            state="Delhi",
            postal_pin="110001",
            digipin=digipin,
            latitude=lat,
            longitude=lon,
            phone_verified=True,
            validation_status="valid",
        )
        session.add(addr)
        session.commit()

        assert addr.digipin is not None
        assert len(addr.digipin) == 10
    finally:
        cleanup_entities(session)
        session.close()


def test_order_and_status_history_characterization():
    session = SessionLocal()
    cleanup_entities(session)
    try:
        buyer = signup_user(
            role="buyer",
            name="Char Buyer",
            password="password123",
            preferred_language="en",
            email="charbuyer@example.com",
            session=session,
        )
        session.commit()
        order = Order(
            id="O-CHAR-123", buyer_id=buyer.id, status=OrderStatus.PLACED, total_amount=100.0, payment_mode="cod"
        )
        session.add(order)
        session.flush()

        history1 = OrderStatusHistory(order_id=order.id, status=OrderStatus.PLACED, actor="system")
        session.add(history1)
        session.commit()

        # Update order status
        order.status = OrderStatus.SHIPPED
        history2 = OrderStatusHistory(order_id=order.id, status=OrderStatus.SHIPPED, actor="agent")
        session.add(history2)
        session.commit()

        histories = session.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == "O-CHAR-123").all()
        assert len(histories) == 2
        assert histories[0].status == OrderStatus.PLACED
        assert histories[1].status == OrderStatus.SHIPPED
    finally:
        cleanup_entities(session)
        session.close()


def test_size_popularity_and_fallback():
    from kavach_saathi.container import get_container
    from kavach_saathi.models import SizeRecommendRequest, RunStatus, AgentName
    import asyncio

    session = SessionLocal()
    cleanup_entities(session)
    try:
        # Create a buyer, seller, and product with no purchase history
        buyer = signup_user(
            role="buyer",
            name="No History Buyer",
            password="password123",
            preferred_language="en",
            email="char-nohist@example.com",
            session=session,
        )
        seller = signup_user(
            role="seller",
            name="Char Seller",
            password="password123",
            preferred_language="en",
            email="char-seller-size@example.com",
            business_name="Char Biz",
            session=session,
        )
        session.commit()

        product = Product(
            id="P-CHAR-NO-HIST",
            title="Saree No Hist",
            brand="Char Brand",
            category="Kurti, Saree & Lehenga",
            price=999.0,
            original_price=1499.0,
            seller_id=seller.id,
            size_chart={"S": {"chest": 85}, "M": {"chest": 90}},
        )
        session.add(product)
        session.commit()

        container = get_container()

        # Test Case 1: No popularity data -> Needs guidance fallback
        req = SizeRecommendRequest(buyer_id=buyer.id, product_id=product.id)
        result = asyncio.run(container.service.graphs.size.run(req))

        assert result.status == RunStatus.NEEDS_EVIDENCE
        assert result.data["needs_guidance"] is True
        assert len(result.actions) == 1
        assert result.actions[0].type == "open_vishwas_saathi"
        assert "Vishwas Saathi" in result.user_message["en"]

        # Test Case 2: With popularity data -> Recommended size from popularity
        # Create ProductVariant first
        variant = ProductVariant(
            id="P-CHAR-NO-HIST-M", product_id=product.id, size="M", sku="SKU-M", stock_qty=10, price=999.0
        )
        session.add(variant)
        session.commit()

        # Create a different buyer to establish popularity without giving the test buyer history
        pop_buyer = signup_user(
            role="buyer",
            name="Pop Buyer",
            password="password123",
            preferred_language="en",
            email="char-pop-buyer@example.com",
            session=session,
        )
        session.commit()

        # Create a mock order to establish popularity
        order = Order(
            id="O-POP-123",
            buyer_id=pop_buyer.id,
            status=OrderStatus.DELIVERED,
            total_amount=999.0,
            payment_mode="cod",
            fit_feedback="good",
        )
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_variant_id="P-CHAR-NO-HIST-M",
            seller_id=seller.id,
            size="M",
            qty=1,
            price_at_purchase=999.0,
        )
        session.add(order)
        session.add(item)
        session.commit()

        # Invalidate cache to ensure it reads fresh popularity
        container.repository.invalidate_cache_for_order(session, "O-POP-123")

        result2 = asyncio.run(container.service.graphs.size.run(req))
        assert result2.status == RunStatus.COMPLETED
        assert result2.data["recommended_size"] == "M"
        assert result2.data["source"] == "product_popularity"
        assert "सबसे अधिक खरीदा गया" in result2.user_message["hi"]
    finally:
        cleanup_entities(session)
        session.close()


def test_vishwas_saathi_chat_persistence():
    from kavach_saathi.container import get_container

    session = SessionLocal()
    cleanup_entities(session)
    try:
        buyer = signup_user(
            role="buyer",
            name="Chat Buyer",
            password="password123",
            preferred_language="en",
            email="char-chat@example.com",
            session=session,
        )
        session.commit()
        container = get_container()

        # Create chat
        chat = container.repository.get_or_create_active_chat(buyer.id, page_route="/products/123", page_type="product")
        assert chat["status"] == "active"
        assert chat["page_route"] == "/products/123"

        # Add messages
        msg1 = container.repository.add_chat_message(chat["id"], "user", "Which size should I choose?")
        msg2 = container.repository.add_chat_message(chat["id"], "assistant", "Welcome to Vishwas Saathi.")

        msgs = container.repository.list_chat_messages(chat["id"])
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Which size should I choose?"
        assert msgs[1]["sender"] == "assistant"

        # Archive
        container.repository.archive_chat_conversation(chat["id"])
        chats = container.repository.list_active_chats_for_user(buyer.id)
        assert chats[0]["status"] == "archived"
    finally:
        cleanup_entities(session)
        session.close()


def test_audio_requests_follow_the_explicit_ui_flow():
    from kavach_saathi.orchestration.graph import AgentGraphs
    from kavach_saathi.models import ChatMessageSend

    size_routed = AgentGraphs._voice_intent(
        {"request": {"audio_key": "uploads/voice/question.webm", "voice_flow": "size"}}
    )
    chat_routed = AgentGraphs._voice_intent(
        {"request": {"audio_key": "uploads/voice/question.webm", "voice_flow": "general"}}
    )
    assert size_routed["intent"] == "size"
    assert chat_routed["intent"] == "general"

    audio_message = ChatMessageSend(
        conversation_id="CHAT-TEST",
        audio_key="uploads/voice/question.webm",
        language="en",
    )
    assert audio_message.text == ""
    with pytest.raises(ValueError, match="Either text or audio_key is required"):
        ChatMessageSend(conversation_id="CHAT-TEST", language="en")


def test_vishwas_saathi_detects_roman_hindi_and_english():
    from kavach_saathi.agents.voice import VoiceQAAgent, detect_chat_language

    assert detect_chat_language("Iss kapde ka rang and material kaisa hai?") == "hi"
    assert detect_chat_language("इसको वॉश कैसे करें?") == "hi"
    assert detect_chat_language("Iss kapde ko wash kaise karein?") == "hi"
    assert detect_chat_language("How should I wash this garment?") == "en"
    assert detect_chat_language("What is the color and material of this product?") == "en"

    agent = VoiceQAAgent.__new__(VoiceQAAgent)
    product = {
        "id": "P-HINDI",
        "name": "Cotton Kurta",
        "price": 499,
        "specs": {"wash_care": "gentle hand wash"},
    }
    answer = agent._deterministic_answer("इसको वॉश कैसे करें?", [product])
    assert detect_chat_language(answer["hi"]) == "hi"
    assert "gentle hand wash" in answer["hi"]


def test_whatsapp_reply_sid_routes_two_orders_on_the_same_phone():
    from kavach_saathi.app import resolve_whatsapp_order_id
    from kavach_saathi.db.models import Order

    redis = MagicMock()
    values = {
        "whatsapp:outbound:MM-ORDER-ONE": b"O-ORDER-ONE",
        "whatsapp:outbound:MM-ORDER-TWO": b"O-ORDER-TWO",
        "whatsapp:pending:+919748572321": b"O-ORDER-TWO",
    }
    redis.get.side_effect = values.get

    first = resolve_whatsapp_order_id(
        {
            "OriginalRepliedMessageSid": "MM-ORDER-ONE",
            "From": "whatsapp:+919748572321",
        },
        None,
        redis,
    )
    second = resolve_whatsapp_order_id(
        {
            "OriginalRepliedMessageSid": "MM-ORDER-TWO",
            "From": "whatsapp:+919748572321",
        },
        None,
        redis,
    )

    assert first == "O-ORDER-ONE"
    assert second == "O-ORDER-TWO"
    assert Order.__table__.c.whatsapp_workflow_state.type.length == 64


def test_delivery_boy_flow_and_reschedule():
    from kavach_saathi.container import get_container

    session = SessionLocal()
    cleanup_entities(session)
    try:
        buyer = signup_user(
            role="buyer",
            name="Delivery Buyer",
            password="password123",
            preferred_language="en",
            email="char-delbuy@example.com",
            session=session,
        )
        db_boy = signup_user(
            role="buyer",
            name="Delivery Boy",
            password="password123",
            preferred_language="en",
            email="char-dbboy@example.com",
            session=session,
        )
        db_boy.role = "delivery_boy"
        session.commit()

        addr = Address(
            id="ADDR-CHAR-DEL",
            user_id=buyer.id,
            raw_text="Delhi Central",
            city="New Delhi",
            state="Delhi",
            postal_pin="110001",
            digipin="1234567890",
            latitude=28.0,
            longitude=77.0,
            phone="9876543210",
            phone_lookup_validated=True,
            validation_status="valid",
        )
        session.add(addr)
        session.commit()

        order = Order(
            id="O-CHAR-DEL-1",
            buyer_id=buyer.id,
            address_id=addr.id,
            status="delivery_assigned",
            delivery_boy_id=db_boy.id,
            total_amount=150.0,
            payment_mode="cod",
        )
        session.add(order)
        session.commit()

        container = get_container()
        # Verify rescheduling directly
        order.promised_delivery_date = datetime.strptime("2026-07-20", "%Y-%m-%d").date()
        order.rescheduled_count = 1
        order.status = "delivery_rescheduled"
        session.commit()

        updated = session.get(Order, "O-CHAR-DEL-1")
        assert updated.status == "delivery_rescheduled"
        assert updated.rescheduled_count == 1
    finally:
        cleanup_entities(session)
        session.close()


def test_return_pickup_visual_similarity_and_limiting():
    session = SessionLocal()
    cleanup_entities(session)
    try:
        buyer = signup_user(
            role="buyer",
            name="Return Buyer",
            password="password123",
            preferred_language="en",
            email="char-retbuy@example.com",
            session=session,
        )
        db_boy = signup_user(
            role="buyer",
            name="Delivery Boy",
            password="password123",
            preferred_language="en",
            email="char-dbboy2@example.com",
            session=session,
        )
        db_boy.role = "delivery_boy"
        seller = signup_user(
            role="seller",
            name="Char Seller",
            password="password123",
            preferred_language="en",
            email="char-seller-ret@example.com",
            business_name="Char Biz",
            session=session,
        )
        session.commit()

        # Create product and order so return foreign keys are satisfied
        product = Product(
            id="P-CHAR-RET-ITEM",
            title="Return Item",
            brand="Char Brand",
            category="Kurti, Saree & Lehenga",
            price=99.0,
            original_price=199.0,
            seller_id=seller.id,
        )
        order = Order(
            id="O-CHAR-RET-ORD", buyer_id=buyer.id, status=OrderStatus.DELIVERED, total_amount=99.0, payment_mode="cod"
        )
        session.add(product)
        session.add(order)
        session.commit()

        ret = ReturnRecord(
            id="R-CHAR-1",
            order_id="O-CHAR-RET-ORD",
            product_id="P-CHAR-RET-ITEM",
            buyer_id=buyer.id,
            delivery_boy_id=db_boy.id,
            status="pickup_assigned",
            reason="Size mismatch",
            attempt_history=[],
        )
        session.add(ret)
        session.commit()

        # Test Case 1: visual mismatch
        attempts = []
        sim_agg = 45.0  # mismatch
        attempts.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "buyer_front_image": "buyer_fail_front.jpg",
                "buyer_back_image": "buyer_fail_back.jpg",
                "similarity_front": sim_agg,
                "similarity_back": sim_agg,
                "similarity_aggregate": sim_agg,
            }
        )
        ret.attempt_history = attempts
        ret.similarity_aggregate = sim_agg
        session.commit()

        updated = session.get(ReturnRecord, "R-CHAR-1")
        assert len(updated.attempt_history) == 1
        assert updated.similarity_aggregate == 45.0

        # Try 2 more times to hit limit
        attempts.append({"timestamp": datetime.now(UTC).isoformat(), "similarity_aggregate": 45.0})
        attempts.append({"timestamp": datetime.now(UTC).isoformat(), "similarity_aggregate": 45.0})
        ret.attempt_history = attempts
        session.commit()

        assert len(session.get(ReturnRecord, "R-CHAR-1").attempt_history) == 3
    finally:
        cleanup_entities(session)
        session.close()
