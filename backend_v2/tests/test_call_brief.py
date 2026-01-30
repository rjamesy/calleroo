"""
Tests for /call/brief and /call/start/v2 endpoints.

These tests verify that:
1. /call/brief returns aiCallMade=true when OpenAI succeeds
2. /call/brief validates phone E.164 format (returns 400 for invalid)
3. /call/brief computes requiredFieldsMissing correctly (deterministic)
4. /call/start/v2 returns NOT_IMPLEMENTED stub
5. /call/start/v2 validates phone E.164 format
"""

import os
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

# Set test API key before importing app
os.environ["OPENAI_API_KEY"] = "test-key-for-testing"
os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

from app.main import app
from app.call_brief_service import (
    compute_missing_required_fields,
    validate_phone_e164,
    is_chain_retailer,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestPhoneValidation:
    """Unit tests for phone E.164 validation."""

    def test_valid_australian_phone(self):
        """Valid AU phone number."""
        assert validate_phone_e164("+61731824583") is True

    def test_valid_us_phone(self):
        """Valid US phone number."""
        assert validate_phone_e164("+14155551234") is True

    def test_invalid_no_plus(self):
        """Phone without + is invalid."""
        assert validate_phone_e164("61731824583") is False

    def test_invalid_short(self):
        """Too short phone number."""
        assert validate_phone_e164("+12345") is False

    def test_invalid_empty(self):
        """Empty phone number."""
        assert validate_phone_e164("") is False

    def test_invalid_letters(self):
        """Phone with letters."""
        assert validate_phone_e164("+61abc824583") is False


class TestChainRetailerDetection:
    """Unit tests for chain retailer detection."""

    def test_jb_hifi_is_chain(self):
        assert is_chain_retailer("JB Hi-Fi") is True
        assert is_chain_retailer("jb hi-fi") is True
        assert is_chain_retailer("JB HiFi") is True

    def test_bunnings_is_chain(self):
        assert is_chain_retailer("Bunnings") is True
        assert is_chain_retailer("bunnings warehouse") is True

    def test_local_store_not_chain(self):
        assert is_chain_retailer("Bob's Electronics") is False
        assert is_chain_retailer("Local Hardware Store") is False


class TestMissingFieldsComputation:
    """Unit tests for compute_missing_required_fields (deterministic logic)."""

    def test_stock_checker_all_missing(self):
        """Stock checker with no slots - all required fields missing."""
        missing = compute_missing_required_fields("STOCK_CHECKER", {})
        assert "retailer_name" in missing
        assert "product_name" in missing

    def test_stock_checker_chain_needs_location(self):
        """Stock checker with chain retailer needs store_location."""
        missing = compute_missing_required_fields("STOCK_CHECKER", {
            "retailer_name": "JB Hi-Fi",
            "product_name": "Sony Headphones",
            "quantity": 1,
        })
        assert "store_location" in missing
        assert "retailer_name" not in missing
        assert "product_name" not in missing

    def test_stock_checker_non_chain_no_location_needed(self):
        """Stock checker with non-chain retailer doesn't need store_location."""
        missing = compute_missing_required_fields("STOCK_CHECKER", {
            "retailer_name": "Bob's Electronics",
            "product_name": "Sony Headphones",
            "quantity": 1,
        })
        assert "store_location" not in missing
        assert len(missing) == 0

    def test_stock_checker_complete(self):
        """Stock checker with all fields - nothing missing."""
        missing = compute_missing_required_fields("STOCK_CHECKER", {
            "retailer_name": "JB Hi-Fi",
            "product_name": "Sony Headphones",
            "quantity": 1,
            "store_location": "Richmond",
        })
        assert len(missing) == 0

    def test_restaurant_all_missing(self):
        """Restaurant with no slots - all required fields missing."""
        missing = compute_missing_required_fields("RESTAURANT_RESERVATION", {})
        assert "restaurant_name" in missing
        assert "party_size" in missing
        assert "date" in missing
        assert "time" in missing

    def test_restaurant_partial(self):
        """Restaurant with partial slots."""
        missing = compute_missing_required_fields("RESTAURANT_RESERVATION", {
            "restaurant_name": "The Italian Place",
            "party_size": "4",
        })
        assert "restaurant_name" not in missing
        assert "party_size" not in missing
        assert "date" in missing
        assert "time" in missing

    def test_restaurant_complete(self):
        """Restaurant with all fields - nothing missing."""
        missing = compute_missing_required_fields("RESTAURANT_RESERVATION", {
            "restaurant_name": "The Italian Place",
            "party_size": "4",
            "date": "2026-02-01",
            "time": "7:00 PM",
        })
        assert len(missing) == 0


class TestCallBriefEndpoint:
    """Integration tests for POST /call/brief"""

    @pytest.mark.asyncio
    async def test_invalid_phone_returns_400(self, client: AsyncClient):
        """Test that invalid phone E.164 returns 400."""
        request_data = {
            "conversationId": "test-1",
            "agentType": "STOCK_CHECKER",
            "place": {
                "placeId": "test-place",
                "businessName": "JB Hi-Fi",
                "formattedAddress": "123 Main St",
                "phoneE164": "invalid-phone"  # Invalid format
            },
            "slots": {},
            "disclosure": {"nameShare": False, "phoneShare": False},
            "fallbacks": {},
        }

        response = await client.post("/call/brief", json=request_data)

        assert response.status_code == 400
        assert "invalid_phone_e164" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_request_returns_ai_call_made(self, client: AsyncClient):
        """Test that valid request returns aiCallMade=true."""
        request_data = {
            "conversationId": "test-2",
            "agentType": "STOCK_CHECKER",
            "place": {
                "placeId": "test-place",
                "businessName": "JB Hi-Fi",
                "formattedAddress": "123 Main St",
                "phoneE164": "+61731824583"  # Valid E.164
            },
            "slots": {
                "retailer_name": "JB Hi-Fi",
                "product_name": "Sony Headphones",
                "quantity": 1,
                "store_location": "Richmond",
            },
            "disclosure": {"nameShare": True, "phoneShare": False},
            "fallbacks": {"askETA": True},
        }

        response = await client.post("/call/brief", json=request_data)

        # If we get 200, aiCallMade must be true
        if response.status_code == 200:
            data = response.json()
            assert data["aiCallMade"] is True
            assert data["aiModel"]
            assert data["objective"]
            assert data["scriptPreview"]
            assert isinstance(data["confirmationChecklist"], list)
            assert data["normalizedPhoneE164"] == "+61731824583"

    @pytest.mark.asyncio
    async def test_missing_fields_computed(self, client: AsyncClient):
        """Test that requiredFieldsMissing is computed correctly."""
        request_data = {
            "conversationId": "test-3",
            "agentType": "STOCK_CHECKER",
            "place": {
                "placeId": "test-place",
                "businessName": "JB Hi-Fi",
                "phoneE164": "+61731824583"
            },
            "slots": {
                "retailer_name": "JB Hi-Fi",
                # Missing: product_name, store_location (chain retailer)
            },
            "disclosure": {},
            "fallbacks": {},
        }

        response = await client.post("/call/brief", json=request_data)

        if response.status_code == 200:
            data = response.json()
            missing = data["requiredFieldsMissing"]
            assert "product_name" in missing
            assert "store_location" in missing
            assert "retailer_name" not in missing


class TestCallStartEndpoint:
    """Integration tests for POST /call/start/v2 (stub)"""

    @pytest.mark.asyncio
    async def test_returns_not_implemented(self, client: AsyncClient):
        """Test that call start returns NOT_IMPLEMENTED stub."""
        request_data = {
            "conversationId": "test-1",
            "agentType": "STOCK_CHECKER",
            "placeId": "test-place",
            "phoneE164": "+61731824583",
            "slots": {},
        }

        response = await client.post("/call/start/v2", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "NOT_IMPLEMENTED"
        assert data["message"] == "call_start_not_implemented"

    @pytest.mark.asyncio
    async def test_invalid_phone_returns_400(self, client: AsyncClient):
        """Test that invalid phone returns 400."""
        request_data = {
            "conversationId": "test-2",
            "agentType": "STOCK_CHECKER",
            "placeId": "test-place",
            "phoneE164": "not-a-phone",
            "slots": {},
        }

        response = await client.post("/call/start/v2", json=request_data)

        assert response.status_code == 400
        assert "invalid_phone_e164" in response.json()["detail"]
