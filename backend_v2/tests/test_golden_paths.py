"""
Golden Path Integration Tests for V2 Conversation Engine.

These tests simulate complete conversation flows and verify:
1. Slot collection order follows AgentSpec
2. extractedData accumulates and never loses keys
3. nextAction progression is deterministic
4. idempotency prevents duplicate processing
5. FIND_PLACE triggers correctly for "don't know" scenarios

Each test represents a realistic user journey through the conversation.
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set test API key before importing app
os.environ["OPENAI_API_KEY"] = "test-key-for-testing"
os.environ["OPENAI_MODEL"] = "gpt-4o-mini"
os.environ["CONVERSATION_ENGINE_VERSION"] = "v2"

from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def mock_extraction_response(extracted_data: dict):
    """Create a mock OpenAI response for extraction."""
    import json
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"extractedData": extracted_data})
    return mock_response


class TestSickCallerGoldenPath:
    """
    3.1 SICK_CALLER (with direct phone) - Complete journey.

    Expected slot order:
    employer_name -> employer_phone -> caller_name -> shift_date ->
    shift_start_time -> reason_category -> CONFIRM -> COMPLETE
    """

    @pytest.mark.asyncio
    async def test_sick_caller_full_progression(self, client: AsyncClient):
        """Test complete SICK_CALLER conversation from start to COMPLETE."""
        conversation_id = "sick-caller-golden-1"
        slots = {}

        # Turn 1: Start -> should ask for employer_name
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": slots,
            "messageHistory": [],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "employer_name"
        assert data["engineVersion"] == "v2"
        assert data["agentMeta"] is not None
        assert data["agentMeta"]["phoneSource"] == "DIRECT_SLOT"

        # Turn 2: Provide employer_name -> should ask for employer_phone
        slots["employer_name"] = "Bunnings Warehouse"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "Bunnings Warehouse",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_name",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "employer_phone"
        # Verify slot accumulation
        assert "employer_name" in data["extractedData"]

        # Turn 3: Provide employer_phone -> should ask for caller_name
        slots["employer_phone"] = "+61412345678"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "0412345678",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_phone",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "caller_name"
        # Verify slot accumulation - previous slots preserved
        assert "employer_name" in data["extractedData"]
        assert "employer_phone" in data["extractedData"]

        # Turn 4: Provide caller_name -> should ask for shift_date
        slots["caller_name"] = "John Smith"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "John Smith",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "caller_name",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "shift_date"
        # Verify all previous slots preserved
        assert "caller_name" in data["extractedData"]

        # Turn 5: Provide shift_date -> should ask for shift_start_time
        slots["shift_date"] = "2026-02-15"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "tomorrow",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "shift_date",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "shift_start_time"

        # Turn 6: Provide shift_start_time -> should ask for reason_category
        slots["shift_start_time"] = "09:00"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "9am",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "shift_start_time",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "reason_category"
        # Verify CHOICE type has quick replies
        assert data["question"]["quickReplies"] is not None
        assert len(data["question"]["quickReplies"]) == 4

        # Turn 7: Provide reason_category -> should show CONFIRM
        slots["reason_category"] = "SICK"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "SICK",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "reason_category",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "CONFIRM"
        assert data["confirmationCard"] is not None
        assert data["confirmationCard"]["cardId"] is not None
        # Verify all 6 required slots are in extractedData
        assert len(data["extractedData"]) >= 6

        # Turn 8: CONFIRM -> should return COMPLETE
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": slots,
            "messageHistory": [],
            "clientAction": "CONFIRM",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "COMPLETE"
        assert data["aiCallMade"] is False
        assert data["aiModel"] == "deterministic"
        # CRITICAL: All slots still preserved after CONFIRM
        assert len(data["extractedData"]) >= 6


class TestSickCallerFindPlace:
    """
    3.2 SICK_CALLER "don't know number" triggers FIND_PLACE.
    """

    @pytest.mark.asyncio
    async def test_dont_know_number_triggers_find_place(self, client: AsyncClient):
        """Test that 'I don't know the number' triggers FIND_PLACE."""
        conversation_id = "sick-caller-find-place-1"
        slots = {"employer_name": "Bunnings Warehouse"}

        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "I don't know the number",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_phone",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "FIND_PLACE"
        assert data["placeSearchParams"] is not None
        # Should use employer_name for place query
        # (SICK_CALLER doesn't have place_query_slot, but should still work)

    @pytest.mark.asyncio
    async def test_can_you_find_triggers_find_place(self, client: AsyncClient):
        """Test that 'can you find it' triggers FIND_PLACE."""
        slots = {"employer_name": "JB Hi-Fi"}

        response = await client.post("/v2/conversation/next", json={
            "conversationId": "sick-caller-find-place-2",
            "agentType": "SICK_CALLER",
            "userMessage": "can you find it for me",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_phone",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "FIND_PLACE"


class TestStockCheckerGoldenPath:
    """
    3.3 STOCK_CHECKER golden path.

    Expected slot order:
    retailer_name -> product_name -> quantity -> store_location -> CONFIRM
    """

    @pytest.mark.asyncio
    async def test_stock_checker_progression(self, client: AsyncClient):
        """Test STOCK_CHECKER slot progression."""
        conversation_id = "stock-checker-golden-1"
        slots = {}

        # Turn 1: Start -> should ask for retailer_name
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "STOCK_CHECKER",
            "userMessage": "",
            "slots": slots,
            "messageHistory": [],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "retailer_name"
        assert data["agentMeta"]["phoneSource"] == "PLACE"

        # Fill all required slots and verify CONFIRM
        slots = {
            "retailer_name": "JB Hi-Fi",
            "product_name": "Sony WH-1000XM5",
            "quantity": "1",
            "store_location": "Sydney CBD",
        }
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "STOCK_CHECKER",
            "userMessage": "Sydney CBD",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "store_location",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "CONFIRM"
        assert data["confirmationCard"] is not None


class TestRestaurantReservationGoldenPath:
    """
    3.4 RESTAURANT_RESERVATION golden path.
    """

    @pytest.mark.asyncio
    async def test_restaurant_reservation_progression(self, client: AsyncClient):
        """Test RESTAURANT_RESERVATION requires key slots."""
        conversation_id = "restaurant-golden-1"

        # Start -> should ask for restaurant_name
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "RESTAURANT_RESERVATION",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "restaurant_name"

        # Fill all required slots -> CONFIRM
        slots = {
            "restaurant_name": "The Italian Place",
            "party_size": "4",
            "date": "2026-02-15",
            "time": "19:00",
        }
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "RESTAURANT_RESERVATION",
            "userMessage": "7pm",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "time",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "CONFIRM"


class TestCancelAppointmentGoldenPath:
    """
    3.5 CANCEL_APPOINTMENT golden path.
    """

    @pytest.mark.asyncio
    async def test_cancel_appointment_progression(self, client: AsyncClient):
        """Test CANCEL_APPOINTMENT requires key slots."""
        conversation_id = "cancel-golden-1"

        # Start -> should ask for business_name
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "CANCEL_APPOINTMENT",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        assert data["question"]["field"] == "business_name"

        # Fill all required slots -> CONFIRM
        slots = {
            "business_name": "City Dental",
            "appointment_day": "2026-02-15",
            "appointment_time": "14:00",
            "customer_name": "Jane Doe",
        }
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "CANCEL_APPOINTMENT",
            "userMessage": "Jane Doe",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "customer_name",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "CONFIRM"


class TestIdempotencySafety:
    """
    3.6 Retry safety - idempotency prevents duplicate processing.
    """

    @pytest.mark.asyncio
    async def test_idempotent_confirm_returns_same_response(self, client: AsyncClient):
        """Test that same idempotencyKey returns identical response."""
        import uuid
        idempotency_key = f"test-idem-{uuid.uuid4()}"

        slots = {
            "employer_name": "Test Corp",
            "employer_phone": "+61412345678",
            "caller_name": "Test User",
            "shift_date": "2026-02-15",
            "shift_start_time": "09:00",
            "reason_category": "SICK",
        }

        # First request
        response1 = await client.post("/v2/conversation/next", json={
            "conversationId": "idem-test-1",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": slots,
            "messageHistory": [],
            "clientAction": "CONFIRM",
            "idempotencyKey": idempotency_key,
        })
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["nextAction"] == "COMPLETE"

        # Second request with SAME idempotency key (should return cached)
        response2 = await client.post("/v2/conversation/next", json={
            "conversationId": "idem-test-1",
            "agentType": "SICK_CALLER",
            "userMessage": "different message",  # Even with different message
            "slots": slots,
            "messageHistory": [],
            "clientAction": "CONFIRM",
            "idempotencyKey": idempotency_key,
        })
        assert response2.status_code == 200
        data2 = response2.json()

        # Should be identical response
        assert data1["nextAction"] == data2["nextAction"]
        assert data1["assistantMessage"] == data2["assistantMessage"]

    @pytest.mark.asyncio
    async def test_different_idempotency_keys_processed_separately(self, client: AsyncClient):
        """Test that different idempotencyKeys are processed independently."""
        import uuid

        slots = {"employer_name": "Test"}

        # First request with key A -> CONFIRM
        response1 = await client.post("/v2/conversation/next", json={
            "conversationId": "idem-test-2a",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {
                "employer_name": "Test",
                "employer_phone": "+61412345678",
                "caller_name": "User",
                "shift_date": "2026-02-15",
                "shift_start_time": "09:00",
                "reason_category": "SICK",
            },
            "messageHistory": [],
            "clientAction": "CONFIRM",
            "idempotencyKey": f"key-{uuid.uuid4()}",
        })
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["nextAction"] == "COMPLETE"

        # Second request with key B -> REJECT
        response2 = await client.post("/v2/conversation/next", json={
            "conversationId": "idem-test-2b",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": slots,
            "messageHistory": [],
            "clientAction": "REJECT",
            "idempotencyKey": f"key-{uuid.uuid4()}",
        })
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["nextAction"] == "ASK_QUESTION"

        # Different results as expected
        assert data1["nextAction"] != data2["nextAction"]


class TestSlotAccumulation:
    """Test that slots never get lost during conversation."""

    @pytest.mark.asyncio
    async def test_slots_never_lost_across_turns(self, client: AsyncClient):
        """Verify extractedData accumulates and never loses keys."""
        conversation_id = "slot-accum-test"

        # Manually progress through turns, checking each time
        slots_seen = set()

        # Turn 1
        slots = {"employer_name": "Company A"}
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "Company A",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_name",
        })
        data = response.json()
        for key in data["extractedData"]:
            slots_seen.add(key)

        # Turn 2
        slots["employer_phone"] = "+61412345678"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "0412345678",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "employer_phone",
        })
        data = response.json()
        # All previously seen slots must still be present
        for key in slots_seen:
            assert key in data["extractedData"], f"Lost slot: {key}"
        for key in data["extractedData"]:
            slots_seen.add(key)

        # Turn 3
        slots["caller_name"] = "John"
        response = await client.post("/v2/conversation/next", json={
            "conversationId": conversation_id,
            "agentType": "SICK_CALLER",
            "userMessage": "John",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "caller_name",
        })
        data = response.json()
        # All previously seen slots must still be present
        for key in slots_seen:
            assert key in data["extractedData"], f"Lost slot: {key}"


class TestEngineVersionField:
    """Test engineVersion field is present in all responses."""

    @pytest.mark.asyncio
    async def test_engine_version_in_normal_response(self, client: AsyncClient):
        """engineVersion is present in normal flow."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "version-test-1",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
        })
        data = response.json()
        assert "engineVersion" in data
        assert data["engineVersion"] == "v2"

    @pytest.mark.asyncio
    async def test_engine_version_in_confirm_response(self, client: AsyncClient):
        """engineVersion is present in CONFIRM response."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "version-test-2",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
            "clientAction": "CONFIRM",
        })
        data = response.json()
        assert data["engineVersion"] == "v2"

    @pytest.mark.asyncio
    async def test_engine_version_in_reject_response(self, client: AsyncClient):
        """engineVersion is present in REJECT response."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "version-test-3",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
            "clientAction": "REJECT",
        })
        data = response.json()
        assert data["engineVersion"] == "v2"


class TestDebugPayload:
    """Tests for debug=true response enhancement (6.3)."""

    @pytest.mark.asyncio
    async def test_debug_payload_present_when_debug_true(self, client: AsyncClient):
        """debug=true should include debugPayload in response."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "test-debug-1",
            "agentType": "SICK_CALLER",
            "userMessage": "Call Bunnings",
            "slots": {},
            "messageHistory": [],
            "debug": True,  # Enable debug
        })

        assert response.status_code == 200
        data = response.json()
        assert data["nextAction"] == "ASK_QUESTION"
        # debugPayload should be present
        assert data.get("debugPayload") is not None
        assert data["debugPayload"]["planner_action"] is not None
        assert isinstance(data["debugPayload"]["merged_slots"], dict)
        assert isinstance(data["debugPayload"]["missing_required_slots"], list)

    @pytest.mark.asyncio
    async def test_debug_payload_absent_when_debug_false(self, client: AsyncClient):
        """debug=false (default) should NOT include debugPayload."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "test-debug-2",
            "agentType": "SICK_CALLER",
            "userMessage": "Call my manager",
            "slots": {},
            "messageHistory": [],
            "debug": False,  # Default
        })

        assert response.status_code == 200
        data = response.json()
        # debugPayload should NOT be present (or None)
        assert data.get("debugPayload") is None

    @pytest.mark.asyncio
    async def test_debug_payload_shows_missing_slots(self, client: AsyncClient):
        """debugPayload should show which required slots are still missing."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "test-debug-3",
            "agentType": "SICK_CALLER",
            "userMessage": "Bunnings",
            "slots": {"employer_name": "Bunnings"},  # Only one slot filled
            "messageHistory": [],
            "debug": True,
        })

        assert response.status_code == 200
        data = response.json()
        assert data.get("debugPayload") is not None
        # Should list missing required slots
        missing = data["debugPayload"]["missing_required_slots"]
        assert len(missing) > 0  # There should be missing slots


class TestAgentMetaAlwaysPresent:
    """Test agentMeta is always present in responses."""

    @pytest.mark.asyncio
    async def test_agent_meta_in_ask_question(self, client: AsyncClient):
        """agentMeta present in ASK_QUESTION response."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "meta-test-1",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
        })
        data = response.json()
        assert data["agentMeta"] is not None
        assert "phoneSource" in data["agentMeta"]

    @pytest.mark.asyncio
    async def test_agent_meta_in_confirm(self, client: AsyncClient):
        """agentMeta present in CONFIRM response."""
        slots = {
            "employer_name": "Test",
            "employer_phone": "+61412345678",
            "caller_name": "User",
            "shift_date": "2026-02-15",
            "shift_start_time": "09:00",
            "reason_category": "SICK",
        }
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "meta-test-2",
            "agentType": "SICK_CALLER",
            "userMessage": "SICK",
            "slots": slots,
            "messageHistory": [],
            "currentQuestionSlotName": "reason_category",
        })
        data = response.json()
        assert data["agentMeta"] is not None

    @pytest.mark.asyncio
    async def test_agent_meta_in_complete(self, client: AsyncClient):
        """agentMeta present in COMPLETE response."""
        response = await client.post("/v2/conversation/next", json={
            "conversationId": "meta-test-3",
            "agentType": "SICK_CALLER",
            "userMessage": "",
            "slots": {},
            "messageHistory": [],
            "clientAction": "CONFIRM",
        })
        data = response.json()
        assert data["agentMeta"] is not None
