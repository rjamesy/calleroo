"""
Calleroo Backend v2 - FastAPI Application

This backend is the SOLE authority for conversation flow.
Every request MUST call OpenAI - no caching, no local heuristics.

Python 3.9 compatible.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .models import (
    ConversationRequest,
    ConversationResponse,
    PlaceSearchRequest,
    PlaceSearchResponse,
    PlaceDetailsRequest,
    PlaceDetailsResponse,
    GeocodeRequest,
    GeocodeResponse,
    CallBriefRequestV2,
    CallBriefResponseV2,
    CallStartRequestV2,
    CallStartResponseV2,
    CallStartRequestV3,
    CallStartResponseV3,
    CallStatusResponseV1,
)
from .openai_service import OpenAIService
from .places_service import GooglePlacesService
from .call_brief_service import (
    get_call_brief_service,
    compute_missing_required_fields,
    validate_phone_e164,
    CallBriefService,
)
from .twilio_service import get_twilio_service, TwilioService, CALL_RUNS

# Load environment variables from backend_v2/.env
# Try multiple paths to ensure we find .env
env_paths = [
    Path(__file__).parent.parent / ".env",  # backend_v2/.env
    Path.cwd() / ".env",  # current working directory
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()  # fallback to default behavior

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Service instances (Python 3.9 compatible type hints)
openai_service: Optional[OpenAIService] = None
places_service: Optional[GooglePlacesService] = None
call_brief_service: Optional[CallBriefService] = None
twilio_service: Optional[TwilioService] = None


def _mask_key(key: Optional[str]) -> str:
    """Mask API key showing only last 4 chars."""
    if not key:
        return "(not set)"
    if len(key) <= 4:
        return "****"
    return f"****{key[-4:]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize services."""
    global openai_service, places_service, call_brief_service, twilio_service

    logger.info("=" * 60)
    logger.info("Initializing Calleroo Backend v2")
    logger.info("=" * 60)

    # Check and log API keys
    openai_key = os.getenv("OPENAI_API_KEY")
    google_key = os.getenv("GOOGLE_PLACES_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    logger.info(f"OPENAI_API_KEY present: {bool(openai_key)} ({_mask_key(openai_key)})")
    logger.info(f"GOOGLE_PLACES_API_KEY present: {bool(google_key)} ({_mask_key(google_key)})")
    logger.info(f"OPENAI_MODEL: {openai_model}")

    # FAIL FAST if OPENAI_API_KEY is missing
    if not openai_key:
        error_msg = (
            "OPENAI_API_KEY is required. "
            "Set it in backend_v2/.env or as an environment variable."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    openai_service = OpenAIService()
    logger.info("OpenAI service initialized successfully")

    call_brief_service = get_call_brief_service()
    logger.info("Call Brief service initialized successfully")

    # Initialize Places service if API key is present
    if google_key:
        places_service = GooglePlacesService()
        logger.info("Google Places service initialized successfully")
    else:
        logger.warning("Google Places service NOT initialized - GOOGLE_PLACES_API_KEY missing")

    # Initialize Twilio service (does NOT crash if not configured)
    twilio_service = get_twilio_service()
    if twilio_service.is_configured:
        logger.info("Twilio service initialized successfully")
    else:
        logger.warning("Twilio service NOT fully configured - calls will fail gracefully")

    logger.info("=" * 60)

    yield

    # Shutdown
    if places_service:
        await places_service.close()
    logger.info("Shutting down Calleroo Backend v2")


app = FastAPI(
    title="Calleroo Backend v2",
    description="Unified conversation API driven entirely by OpenAI",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "2.0.0"}


@app.post("/conversation/next", response_model=ConversationResponse)
async def conversation_next(request: ConversationRequest) -> ConversationResponse:
    """
    Process the next turn in a conversation.

    CRITICAL: This endpoint ALWAYS calls OpenAI.
    - NO local question logic
    - NO pre-extraction heuristics
    - NO fallback flows

    The backend is the sole authority for:
    - Assistant message text
    - Next action
    - Question (text/field/inputType/choices/optional)
    - Extracted slots

    The Android client MUST NOT decide questions, slots, flow order, or "what to ask next".
    """
    msg_preview = request.userMessage[:50] + "..." if len(request.userMessage) > 50 else request.userMessage
    logger.info(
        f"Conversation turn: id={request.conversationId}, "
        f"agent={request.agentType}, "
        f"message='{msg_preview}'"
    )

    if openai_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        # ALWAYS call OpenAI - this is non-negotiable
        # NO local heuristics, NO pre-extraction, NO fallbacks
        response = await openai_service.get_next_turn(
            agent_type=request.agentType,
            user_message=request.userMessage,
            slots=request.slots,
            message_history=request.messageHistory,
        )

        # Verify OpenAI was actually called
        if not response.aiCallMade:
            logger.error("CRITICAL: Response indicates aiCallMade=false, this should never happen")
            raise HTTPException(
                status_code=500,
                detail="openai_not_called: Backend must always call OpenAI"
            )

        # Log the response
        logger.info(
            f"Response: action={response.nextAction}, "
            f"aiCallMade={response.aiCallMade}, "
            f"model={response.aiModel}"
        )

        if request.debug:
            logger.debug(f"Full response: {response.model_dump_json()}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing conversation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"openai_failed: {str(e)}"
        )


# ============================================================
# Place Search Endpoints (Screen 3 - NO OpenAI, deterministic)
# ============================================================

# Allowed radius values for place search
ALLOWED_RADII = [25, 50, 100]


@app.post("/places/geocode", response_model=GeocodeResponse)
async def places_geocode(request: GeocodeRequest) -> GeocodeResponse:
    """
    Geocode an area name to lat/lng coordinates.

    This endpoint does NOT call OpenAI - it is deterministic.
    Uses Google Geocoding API.

    Returns:
        GeocodeResponse with lat/lng or error
    """
    logger.info(f"Places geocode: area='{request.area}', country='{request.country}'")

    if places_service is None:
        raise HTTPException(
            status_code=500,
            detail="places_key_missing: GOOGLE_PLACES_API_KEY not configured"
        )

    try:
        response = await places_service.geocode(
            area=request.area,
            country=request.country,
        )

        logger.info(
            f"Geocode result: lat={response.latitude}, lng={response.longitude}, "
            f"error={response.error}"
        )

        return response

    except Exception as e:
        logger.error(f"Geocode error: {e}", exc_info=True)
        # Return 200 with error in body per spec
        return GeocodeResponse(
            latitude=0.0,
            longitude=0.0,
            formattedAddress="",
            error=f"geocode_failed: {str(e)}"
        )


@app.post("/places/search", response_model=PlaceSearchResponse)
async def places_search(request: PlaceSearchRequest) -> PlaceSearchResponse:
    """
    Search for places matching the query in the specified area.

    This endpoint does NOT call OpenAI - it is deterministic.
    Uses Google Places Text Search API with area geocoding.

    Returns only candidates (does not filter by phone number here).
    Client should call /places/details to get phone number.

    Radius must be 25, 50, or 100 km - returns 400 for invalid values.
    """
    logger.info(
        f"Places search: query='{request.query}', "
        f"area='{request.area}', "
        f"radius={request.radius_km}km"
    )

    # Validate radius - return 400 for invalid values
    if request.radius_km not in ALLOWED_RADII:
        logger.warning(f"Invalid radius {request.radius_km}km, rejecting with 400")
        raise HTTPException(
            status_code=400,
            detail=f"invalid_radius: radius_km must be one of {ALLOWED_RADII}, got {request.radius_km}"
        )

    if places_service is None:
        raise HTTPException(
            status_code=500,
            detail="places_key_missing: GOOGLE_PLACES_API_KEY not configured"
        )

    try:
        response = await places_service.text_search(
            query=request.query,
            area=request.area,
            country=request.country,
            radius_km=request.radius_km,
        )

        logger.info(
            f"Places search result: {len(response.candidates)} candidates, "
            f"radius={response.radiusKm}km, pass={response.passNumber}, "
            f"error={response.error}"
        )

        return response

    except Exception as e:
        logger.error(f"Places search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"places_search_failed: {str(e)}"
        )


@app.post("/places/details", response_model=PlaceDetailsResponse)
async def places_details(request: PlaceDetailsRequest) -> PlaceDetailsResponse:
    """
    Get detailed information about a specific place.

    This endpoint does NOT call OpenAI - it is deterministic.
    Uses Google Places Details API.

    Returns phoneE164 if the place has a valid phone number.
    Returns error="NO_PHONE" if the place has no valid phone.
    """
    logger.info(f"Places details: placeId='{request.placeId}'")

    if places_service is None:
        raise HTTPException(
            status_code=500,
            detail="places_key_missing: GOOGLE_PLACES_API_KEY not configured"
        )

    try:
        response = await places_service.place_details(request.placeId)

        logger.info(
            f"Places details result: name='{response.name}', "
            f"phoneE164={response.phoneE164 or 'None'}, "
            f"error={response.error}"
        )

        return response

    except Exception as e:
        logger.error(f"Places details error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"places_details_failed: {str(e)}"
        )


# ============================================================
# Call Brief Endpoints (Screen 4 - OpenAI generates call script)
# ============================================================

@app.post("/call/brief", response_model=CallBriefResponseV2)
async def call_brief(request: CallBriefRequestV2) -> CallBriefResponseV2:
    """
    Generate a call brief with script preview.

    This endpoint ALWAYS calls OpenAI to generate:
    - objective: Short description of call purpose
    - scriptPreview: Plain text call script preview
    - confirmationChecklist: Items user should verify

    Deterministically computes:
    - requiredFieldsMissing: Based on agent type and slots

    Validates:
    - phoneE164: Must be valid E.164 format

    Returns 400 for invalid phone number.
    """
    logger.info(
        f"Call brief: conversationId={request.conversationId}, "
        f"agentType={request.agentType}, "
        f"place={request.place.businessName}"
    )

    # Validate phone E.164 format
    if not validate_phone_e164(request.place.phoneE164):
        logger.warning(f"Invalid phone E.164: {request.place.phoneE164}")
        raise HTTPException(
            status_code=400,
            detail=f"invalid_phone_e164: Phone must be E.164 format (e.g., +61731824583), got: {request.place.phoneE164}"
        )

    if call_brief_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        # Compute missing required fields (deterministic, NOT OpenAI)
        missing_fields = compute_missing_required_fields(
            agent_type=request.agentType,
            slots=request.slots,
        )

        # ALWAYS call OpenAI to generate the brief
        objective, script_preview, checklist = await call_brief_service.generate_brief(
            agent_type=request.agentType,
            place=request.place,
            slots=request.slots,
            disclosure=request.disclosure,
            fallbacks=request.fallbacks,
        )

        response = CallBriefResponseV2(
            objective=objective,
            scriptPreview=script_preview,
            confirmationChecklist=checklist,
            normalizedPhoneE164=request.place.phoneE164,  # Already validated
            requiredFieldsMissing=missing_fields,
            aiCallMade=True,
            aiModel=call_brief_service.model,
        )

        logger.info(
            f"Call brief generated: objective='{objective[:50]}...', "
            f"missingFields={missing_fields}, "
            f"checklistItems={len(checklist)}"
        )

        if request.debug:
            logger.debug(f"Full call brief response: {response.model_dump_json()}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Call brief error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"call_brief_failed: {str(e)}"
        )


@app.post("/call/start/v2", response_model=CallStartResponseV2)
async def call_start_v2(request: CallStartRequestV2) -> CallStartResponseV2:
    """
    Start a call (STUB for Step 3).

    This endpoint validates the phone number but does NOT actually initiate a call.
    Twilio integration will be added in a future step.

    Returns a stub response indicating the call is not yet implemented.
    """
    logger.info(
        f"Call start (stub): conversationId={request.conversationId}, "
        f"agentType={request.agentType}, "
        f"placeId={request.placeId}, "
        f"phone={request.phoneE164}"
    )

    # Validate phone E.164 format
    if not validate_phone_e164(request.phoneE164):
        logger.warning(f"Invalid phone E.164: {request.phoneE164}")
        raise HTTPException(
            status_code=400,
            detail=f"invalid_phone_e164: Phone must be E.164 format, got: {request.phoneE164}"
        )

    # STUB: Return not implemented response
    # Twilio integration will be added in a future step
    logger.info("Call start stub - returning NOT_IMPLEMENTED")

    return CallStartResponseV2(
        status="NOT_IMPLEMENTED",
        message="call_start_not_implemented"
    )


# ============================================================
# Call Start V3 Endpoints (Step 4 - Real Twilio Calls)
# ============================================================

@app.post("/call/start", response_model=CallStartResponseV3)
async def call_start(request: CallStartRequestV3) -> CallStartResponseV3:
    """
    Start a real outbound call via Twilio.

    This endpoint:
    1. Validates the phone number (E.164 format)
    2. Initiates a Twilio call
    3. Returns the call ID for status polling

    Returns:
        CallStartResponseV3 with callId and initial status

    Errors:
        400: Invalid phone number
        503: Twilio not configured
    """
    logger.info(
        f"Call start V3: conversationId={request.conversationId}, "
        f"agentType={request.agentType}, "
        f"placeId={request.placeId}, "
        f"phone={request.phoneE164}"
    )

    # Validate phone E.164 format
    if not validate_phone_e164(request.phoneE164):
        logger.warning(f"Invalid phone E.164: {request.phoneE164}")
        raise HTTPException(
            status_code=400,
            detail=f"invalid_phone_e164: Phone must be E.164 format, got: {request.phoneE164}"
        )

    if twilio_service is None or not twilio_service.is_configured:
        logger.error("Twilio service not configured")
        raise HTTPException(
            status_code=503,
            detail="twilio_not_configured: Twilio credentials are missing"
        )

    try:
        call_run = twilio_service.start_call(
            conversation_id=request.conversationId,
            agent_type=request.agentType,
            phone_e164=request.phoneE164,
            script_preview=request.scriptPreview,
            slots=request.slots,
        )

        return CallStartResponseV3(
            callId=call_run.call_id,
            status=call_run.status,
            message="Call initiated successfully"
        )

    except RuntimeError as e:
        logger.error(f"Call start failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"twilio_error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Call start error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"call_start_failed: {str(e)}"
        )


@app.get("/call/status/{call_id}", response_model=CallStatusResponseV1)
async def call_status(call_id: str) -> CallStatusResponseV1:
    """
    Get the status of a call.

    Returns the current status, and if completed, includes:
    - transcript (from Whisper)
    - outcome (from OpenAI analysis)
    - duration

    Returns:
        CallStatusResponseV1 with current status and results

    Errors:
        404: Call not found
    """
    logger.debug(f"Call status request: callId={call_id}")

    # Get call run from in-memory storage (works even if Twilio not configured)
    call_run = CALL_RUNS.get(call_id)
    if not call_run:
        logger.warning(f"Call not found: {call_id}")
        raise HTTPException(
            status_code=404,
            detail=f"call_not_found: No call with ID {call_id}"
        )

    return CallStatusResponseV1(
        callId=call_run.call_id,
        status=call_run.status,
        durationSeconds=call_run.duration_seconds,
        transcript=call_run.transcript,
        outcome=call_run.outcome,
        error=call_run.error,
    )


# ============================================================
# Twilio Webhooks (Step 4)
# ============================================================

def _escape_xml(text: str) -> str:
    """Escape text for XML."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@app.post("/twilio/voice")
async def twilio_voice(conversationId: str = Query(...)):
    """
    Twilio voice webhook - called when call connects.

    Returns TwiML with the script to speak.

    Args:
        conversationId: Conversation ID from query param
    """
    logger.info(f"Twilio voice webhook: conversationId={conversationId}")

    # Find the call run by conversation_id
    call_run = None
    for run in CALL_RUNS.values():
        if run.conversation_id == conversationId:
            call_run = run
            break

    if call_run:
        script = call_run.script_preview
    else:
        script = "Hello, this is Calleroo. I apologize, but there was a technical issue. Please have a nice day."
        logger.warning(f"No call run found for conversation {conversationId}")

    # Build TwiML with Australian English voice
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew" language="en-AU">{_escape_xml(script)}</Say>
    <Pause length="2"/>
    <Say voice="Polly.Matthew" language="en-AU">Thank you for your time. Goodbye.</Say>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@app.post("/twilio/status")
async def twilio_status(
    background_tasks: BackgroundTasks,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(None),
):
    """
    Twilio status callback webhook.

    Called by Twilio when call status changes:
    - initiated, ringing, in-progress, completed, busy, no-answer, failed, canceled

    On completion, triggers async transcription and outcome analysis.
    """
    duration = int(CallDuration) if CallDuration else None
    logger.info(f"Twilio status webhook: CallSid={CallSid}, status={CallStatus}, duration={duration}")

    # Update call status directly in CALL_RUNS
    call_run = CALL_RUNS.get(CallSid)
    if call_run:
        call_run.status = CallStatus
        if duration is not None:
            call_run.duration_seconds = duration
        logger.info(f"Call {CallSid} status updated to {CallStatus}")

        # If completed and twilio_service available, trigger async processing
        if CallStatus == "completed" and twilio_service is not None:
            background_tasks.add_task(twilio_service.process_completed_call, CallSid)
    else:
        logger.warning(f"twilio_status: Unknown call_id {CallSid}")

    return {"status": "ok"}


@app.post("/twilio/recording")
async def twilio_recording(
    background_tasks: BackgroundTasks,
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(None),
):
    """
    Twilio recording status callback webhook.

    Called when recording is available.
    Stores the recording URL and triggers transcription if call is completed.
    """
    logger.info(f"Twilio recording webhook: CallSid={CallSid}, status={RecordingStatus}, url={RecordingUrl}")

    # Store recording URL directly in CALL_RUNS
    call_run = CALL_RUNS.get(CallSid)
    if call_run:
        call_run.recording_url = RecordingUrl
        logger.info(f"Call {CallSid} recording URL stored")

        # Check if call is already completed, if so trigger processing
        if call_run.status == "completed" and not call_run.transcript and twilio_service is not None:
            background_tasks.add_task(twilio_service.process_completed_call, CallSid)
    else:
        logger.warning(f"twilio_recording: Unknown call_id {CallSid}")

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
