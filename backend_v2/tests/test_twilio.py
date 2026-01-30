"""
Tests for Twilio integration endpoints (Step 4).

These tests verify that:
1. POST /call/start validates phone E.164 format
2. POST /call/start returns 503 when Twilio not configured
3. GET /call/status/{call_id} returns 404 for unknown calls
4. POST /twilio/voice returns valid TwiML
5. POST /twilio/status handles status updates
"""

import os
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

# Set test API key before importing app
os.environ["OPENAI_API_KEY"] = "test-key-for-testing"
os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

# NOTE: Twilio credentials are intentionally NOT set in tests
# This tests graceful degradation behavior

from app.main import app
from app.twilio_service import CALL_RUNS, CallRun, get_twilio_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture(autouse=True)
def clear_call_runs():
    """Clear CALL_RUNS before each test."""
    CALL_RUNS.clear()
    yield
    CALL_RUNS.clear()


class TestCallStartEndpoint:
    """Tests for POST /call/start (V3 - real Twilio calls)"""

    @pytest.mark.asyncio
    async def test_invalid_phone_returns_400(self, client: AsyncClient):
        """Test that invalid phone E.164 returns 400."""
        request_data = {
            "conversationId": "test-1",
            "agentType": "STOCK_CHECKER",
            "placeId": "test-place",
            "phoneE164": "not-a-phone",
            "slots": {},
            "scriptPreview": "Hello, this is a test."
        }

        response = await client.post("/call/start", json=request_data)

        assert response.status_code == 400
        assert "invalid_phone_e164" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_twilio_not_configured_returns_503(self, client: AsyncClient):
        """Test that unconfigured Twilio returns 503."""
        request_data = {
            "conversationId": "test-1",
            "agentType": "STOCK_CHECKER",
            "placeId": "test-place",
            "phoneE164": "+61731824583",
            "slots": {},
            "scriptPreview": "Hello, this is a test call."
        }

        response = await client.post("/call/start", json=request_data)

        # Should return 503 because Twilio credentials are not set
        assert response.status_code == 503
        assert "twilio" in response.json()["detail"].lower()


class TestCallStatusEndpoint:
    """Tests for GET /call/status/{call_id}"""

    @pytest.mark.asyncio
    async def test_call_not_found_returns_404(self, client: AsyncClient):
        """Test that unknown call_id returns 404."""
        response = await client.get("/call/status/unknown-call-id")

        assert response.status_code == 404
        assert "call_not_found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_call_found_returns_status(self, client: AsyncClient):
        """Test that known call_id returns status."""
        # Add a call run directly to storage
        call_run = CallRun(
            call_id="test-call-123",
            conversation_id="conv-1",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Hello, test script.",
            status="in-progress",
            duration_seconds=30,
        )
        CALL_RUNS["test-call-123"] = call_run

        response = await client.get("/call/status/test-call-123")

        assert response.status_code == 200
        data = response.json()
        assert data["callId"] == "test-call-123"
        assert data["status"] == "in-progress"
        assert data["durationSeconds"] == 30

    @pytest.mark.asyncio
    async def test_completed_call_includes_transcript(self, client: AsyncClient):
        """Test that completed call includes transcript and outcome."""
        call_run = CallRun(
            call_id="test-call-456",
            conversation_id="conv-2",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Hello, test script.",
            status="completed",
            duration_seconds=60,
            transcript="Yes, we have that item in stock.",
            outcome={
                "success": True,
                "summary": "Item is in stock",
                "extractedFacts": {"inStock": True},
                "confidence": "HIGH"
            },
        )
        CALL_RUNS["test-call-456"] = call_run

        response = await client.get("/call/status/test-call-456")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["transcript"] == "Yes, we have that item in stock."
        assert data["outcome"]["success"] is True
        assert data["outcome"]["extractedFacts"]["inStock"] is True


class TestTwilioVoiceWebhook:
    """Tests for POST /twilio/voice webhook"""

    @pytest.mark.asyncio
    async def test_returns_twiml(self, client: AsyncClient):
        """Test that voice webhook returns TwiML XML."""
        # Add a call run for the conversation
        call_run = CallRun(
            call_id="twilio-sid-789",
            conversation_id="test-conv",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Hello, I am calling about a product.",
        )
        CALL_RUNS["twilio-sid-789"] = call_run

        response = await client.post("/twilio/voice?conversationId=test-conv")

        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "<Response>" in response.text
        assert "<Say" in response.text
        assert "Hello, I am calling about a product." in response.text

    @pytest.mark.asyncio
    async def test_unknown_conversation_returns_fallback(self, client: AsyncClient):
        """Test that unknown conversation returns fallback TwiML."""
        response = await client.post("/twilio/voice?conversationId=unknown")

        assert response.status_code == 200
        assert "<Response>" in response.text
        assert "technical issue" in response.text


class TestTwilioStatusWebhook:
    """Tests for POST /twilio/status webhook"""

    @pytest.mark.asyncio
    async def test_status_update(self, client: AsyncClient):
        """Test that status webhook updates call status."""
        # Add a call run
        call_run = CallRun(
            call_id="twilio-sid-status",
            conversation_id="conv-status",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Test script",
            status="queued",
        )
        CALL_RUNS["twilio-sid-status"] = call_run

        # Send status update via form data
        response = await client.post(
            "/twilio/status",
            data={
                "CallSid": "twilio-sid-status",
                "CallStatus": "in-progress",
            }
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify status was updated
        assert CALL_RUNS["twilio-sid-status"].status == "in-progress"

    @pytest.mark.asyncio
    async def test_completed_status_with_duration(self, client: AsyncClient):
        """Test that completed status includes duration."""
        call_run = CallRun(
            call_id="twilio-sid-complete",
            conversation_id="conv-complete",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Test script",
            status="in-progress",
        )
        CALL_RUNS["twilio-sid-complete"] = call_run

        response = await client.post(
            "/twilio/status",
            data={
                "CallSid": "twilio-sid-complete",
                "CallStatus": "completed",
                "CallDuration": "45",
            }
        )

        assert response.status_code == 200

        # Verify status and duration updated
        updated = CALL_RUNS["twilio-sid-complete"]
        assert updated.status == "completed"
        assert updated.duration_seconds == 45


class TestTwilioRecordingWebhook:
    """Tests for POST /twilio/recording webhook"""

    @pytest.mark.asyncio
    async def test_recording_url_stored(self, client: AsyncClient):
        """Test that recording URL is stored."""
        call_run = CallRun(
            call_id="twilio-sid-rec",
            conversation_id="conv-rec",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Test script",
            status="in-progress",
        )
        CALL_RUNS["twilio-sid-rec"] = call_run

        response = await client.post(
            "/twilio/recording",
            data={
                "CallSid": "twilio-sid-rec",
                "RecordingUrl": "https://api.twilio.com/recordings/123.mp3",
                "RecordingStatus": "completed",
            }
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify recording URL was stored
        assert CALL_RUNS["twilio-sid-rec"].recording_url == "https://api.twilio.com/recordings/123.mp3"


class TestTwilioServiceUnit:
    """Unit tests for TwilioService"""

    def test_service_graceful_degradation(self):
        """Test that service doesn't crash when Twilio not configured."""
        service = get_twilio_service()
        # Should not raise, just return unconfigured service
        assert service is not None
        # is_configured should be False when credentials missing
        # (depends on env vars being set)

    def test_twiml_escapes_xml(self):
        """Test that TwiML generation escapes special XML characters."""
        service = get_twilio_service()

        # Add a call run with XML special characters
        call_run = CallRun(
            call_id="test-xml",
            conversation_id="conv-xml",
            agent_type="STOCK_CHECKER",
            phone_e164="+61731824583",
            script_preview="Do you have <product> with 5 & 10 items?",
        )
        CALL_RUNS["test-xml"] = call_run

        twiml = service.generate_twiml("conv-xml")

        # Verify XML is properly escaped
        assert "&lt;product&gt;" in twiml
        assert "&amp;" in twiml
        assert "<product>" not in twiml  # Should be escaped
