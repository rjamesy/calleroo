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
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .models import (
    ClientAction,
    Confidence,
    ConversationRequest,
    ConversationResponse,
    NextAction,
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
    CallResultFormatRequestV1,
    CallResultFormatResponseV1,
)
from .openai_service import OpenAIService
from .places_service import GooglePlacesService
from .call_brief_service import (
    get_call_brief_service,
    compute_missing_required_fields,
    validate_phone_e164,
    CallBriefService,
)
from .twilio_service import get_twilio_service, TwilioService, CALL_RUNS, HOLD_ACKNOWLEDGEMENT, _is_pure_hold_phrase
from .call_result_service import get_call_result_service, CallResultService

# Filler phrases for immediate response (filler/poll pattern)
FILLER_PHRASES = [
    "One moment.",
    "Just a sec.",
    "Ummmmmm.",
    "Ummm, one sec.",
]

POLL_FILLER_PHRASES = [
    "Still checking.",
    "Almost there.",
    "One moment.",
    "Just a sec.",
]

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
call_result_service: Optional[CallResultService] = None

# Idempotency store for preventing duplicate confirmations
# Key: idempotencyKey, Value: (response, timestamp)
# In production, use Redis or a database
from typing import Dict, Tuple
from datetime import datetime, timedelta

_idempotency_store: Dict[str, Tuple[ConversationResponse, datetime]] = {}
_IDEMPOTENCY_TTL = timedelta(minutes=5)


def _get_idempotent_response(key: str) -> Optional[ConversationResponse]:
    """Get cached response for idempotency key if still valid."""
    if key in _idempotency_store:
        response, timestamp = _idempotency_store[key]
        if datetime.now() - timestamp < _IDEMPOTENCY_TTL:
            logger.info(f"Idempotency hit for key={key}")
            return response
        else:
            # Expired, remove it
            del _idempotency_store[key]
    return None


def _store_idempotent_response(key: str, response: ConversationResponse) -> None:
    """Store response for idempotency."""
    _idempotency_store[key] = (response, datetime.now())
    # Clean up old entries (simple LRU-ish cleanup)
    if len(_idempotency_store) > 1000:
        cutoff = datetime.now() - _IDEMPOTENCY_TTL
        keys_to_remove = [k for k, (_, ts) in _idempotency_store.items() if ts < cutoff]
        for k in keys_to_remove:
            del _idempotency_store[k]


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
    global openai_service, places_service, call_brief_service, twilio_service, call_result_service

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

    # Initialize Call Result service
    call_result_service = get_call_result_service()
    logger.info("Call Result service initialized successfully")

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


# Required slots per agent type for fallback question generation
REQUIRED_SLOTS_MAP = {
    # (field_name, question_text, input_type)
    "SICK_CALLER": [
        ("employer_name", "Who should I call to notify?", "TEXT"),
        ("employer_phone", "What's their phone number?", "PHONE"),
        ("caller_name", "What name should I give them?", "TEXT"),
        ("shift_date", "When is your shift?", "DATE"),
        ("shift_start_time", "What time does it start?", "TIME"),
        ("reason_category", "What's the reason?", "CHOICE"),
    ],
    "STOCK_CHECKER": [
        ("retailer_name", "Which retailer should I call?", "TEXT"),
        ("product_name", "What product are you looking for?", "TEXT"),
        ("quantity", "How many do you need?", "NUMBER"),
        ("store_location", "Which suburb or area?", "TEXT"),
    ],
    "RESTAURANT_RESERVATION": [
        ("restaurant_name", "Which restaurant would you like to book?", "TEXT"),
        ("party_size", "How many people?", "NUMBER"),
        ("date", "What date?", "DATE"),
        ("time", "What time?", "TIME"),
    ],
    "CANCEL_APPOINTMENT": [
        ("business_name", "What's the name of the business?", "TEXT"),
        ("appointment_day", "What day is the appointment?", "DATE"),
        ("appointment_time", "What time is the appointment?", "TIME"),
        ("customer_name", "What name is the booking under?", "TEXT"),
    ],
}


def _get_next_missing_slot(agent_type: str, slots: dict, conversation_id: str = "unknown") -> tuple:
    """Find the next missing required slot for an agent type.

    Returns (field, question_text, input_type) or None if all present.

    CRITICAL: slots should be the MERGED slots (existing + extractedData)
    to avoid asking for a slot that was just extracted.
    """
    required = REQUIRED_SLOTS_MAP.get(agent_type, [])
    filled_slots = [f for f, _, _ in required if f in slots and slots.get(f)]
    missing_slots = [f for f, _, _ in required if f not in slots or not slots.get(f)]

    for field, question_text, input_type in required:
        if field not in slots or not slots.get(field):
            # Log for debugging
            logger.debug(
                f"nextMissingSlot: agent={agent_type}, "
                f"filled={filled_slots}, missing={missing_slots}, "
                f"next={field}, conversationId={conversation_id}"
            )
            return (field, question_text, input_type)

    logger.debug(
        f"nextMissingSlot: agent={agent_type}, "
        f"filled={filled_slots}, missing=[], next=None (all complete), "
        f"conversationId={conversation_id}"
    )
    return None


def _create_endpoint_fallback_response(
    agent_type: str,
    slots: dict,
    conversation_id: str,
) -> ConversationResponse:
    """Create a safe fallback response when unexpected errors occur.

    This is the FINAL safety net - used only when all else fails.
    """
    from .models import Question, InputType, Confidence

    next_slot = _get_next_missing_slot(agent_type, slots, conversation_id)

    if next_slot:
        field, question_text, input_type_str = next_slot
        try:
            input_type = InputType(input_type_str)
        except ValueError:
            input_type = InputType.TEXT

        question = Question(
            text=question_text,
            field=field,
            inputType=input_type,
            choices=None,
            optional=False,
        )
        assistant_message = question_text
    else:
        question = Question(
            text="Could you please provide more details?",
            field="additional_info",
            inputType=InputType.TEXT,
            choices=None,
            optional=True,
        )
        assistant_message = "I need a bit more information to continue."

    logger.warning(
        f"METRIC endpoint_fallback_used agent={agent_type} "
        f"conversationId={conversation_id} next_field={question.field}"
    )

    return ConversationResponse(
        assistantMessage=assistant_message,
        nextAction=NextAction.ASK_QUESTION,
        question=question,
        extractedData=None,
        confidence=Confidence.LOW,
        confirmationCard=None,
        placeSearchParams=None,
        aiCallMade=True,
        aiModel="fallback",
    )


def sanitize_conversation_response(
    response: ConversationResponse,
    conversation_id: str,
    agent_type: str,
    slots: dict = None,
) -> ConversationResponse:
    """
    Validate and auto-repair conversation response for schema completeness.
    Logs warnings and returns a sanitized response.

    CRITICAL: mergedSlots = existing_slots + extractedData is used for nextMissingSlot.
    This ensures we don't ask for slots the model just extracted.

    Auto-repairs:
    - FIND_PLACE without placeSearchParams -> ASK_QUESTION with generated question
    - CONFIRM without confirmationCard -> ASK_QUESTION with generated question
    - Empty assistantMessage -> use question.text or fallback message
    - Conflicting blocks (e.g., FIND_PLACE with question) -> drop irrelevant blocks
    - ASK_QUESTION without question -> generate question for next missing slot
    - extractedData null -> normalize to {}
    """
    from .models import Question, InputType, Confidence

    if slots is None:
        slots = {}

    # CRITICAL FIX: Merge existing slots with extractedData BEFORE computing nextMissingSlot
    # This prevents asking for a slot that was just extracted
    extracted_data = response.extractedData if response.extractedData else {}
    merged_slots = {**slots, **extracted_data}

    # Log for debugging slot merge issues
    if extracted_data:
        logger.debug(
            f"Slot merge: existing={list(slots.keys())}, "
            f"extracted={list(extracted_data.keys())}, "
            f"merged={list(merged_slots.keys())} "
            f"conversationId={conversation_id}"
        )

    warnings = []
    repairs = []

    # Check and repair nextAction combinations
    next_action = response.nextAction
    confirmation_card = response.confirmationCard
    place_search_params = response.placeSearchParams
    question = response.question
    assistant_message = response.assistantMessage

    # Handle conflicting blocks: nextAction takes precedence
    if next_action == NextAction.FIND_PLACE:
        if place_search_params is None:
            warnings.append("FIND_PLACE_missing_placeSearchParams")
            next_action = NextAction.ASK_QUESTION
            repairs.append("downgraded_to_ASK_QUESTION")
            # Generate a question for next missing slot (using merged_slots!)
            next_slot = _get_next_missing_slot(agent_type, merged_slots, conversation_id)
            if next_slot:
                field, q_text, input_type_str = next_slot
                try:
                    input_type = InputType(input_type_str)
                except ValueError:
                    input_type = InputType.TEXT
                question = Question(
                    text=q_text,
                    field=field,
                    inputType=input_type,
                    choices=None,
                    optional=False,
                )
                assistant_message = q_text
                repairs.append("generated_question_for_missing_slot")
            else:
                assistant_message = "I need more information. What's the name of the business you'd like to call?"
        elif question is not None:
            # Conflicting: FIND_PLACE should not have question
            warnings.append("FIND_PLACE_has_conflicting_question")
            question = None
            repairs.append("dropped_question_for_FIND_PLACE")

    elif next_action == NextAction.CONFIRM:
        if confirmation_card is None:
            warnings.append("CONFIRM_missing_confirmationCard")
            next_action = NextAction.ASK_QUESTION
            repairs.append("downgraded_to_ASK_QUESTION")
            # Generate a question for next missing slot (using merged_slots!)
            next_slot = _get_next_missing_slot(agent_type, merged_slots, conversation_id)
            if next_slot:
                field, q_text, input_type_str = next_slot
                try:
                    input_type = InputType(input_type_str)
                except ValueError:
                    input_type = InputType.TEXT
                question = Question(
                    text=q_text,
                    field=field,
                    inputType=input_type,
                    choices=None,
                    optional=False,
                )
                assistant_message = q_text
                repairs.append("generated_question_for_missing_slot")
        elif question is not None:
            # Conflicting: CONFIRM should not have question
            warnings.append("CONFIRM_has_conflicting_question")
            question = None
            repairs.append("dropped_question_for_CONFIRM")

    elif next_action == NextAction.ASK_QUESTION:
        if question is None:
            warnings.append("ASK_QUESTION_missing_question")
            # Generate a question for next missing slot (using merged_slots!)
            next_slot = _get_next_missing_slot(agent_type, merged_slots, conversation_id)
            if next_slot:
                field, q_text, input_type_str = next_slot
                try:
                    input_type = InputType(input_type_str)
                except ValueError:
                    input_type = InputType.TEXT
                question = Question(
                    text=q_text,
                    field=field,
                    inputType=input_type,
                    choices=None,
                    optional=False,
                )
                repairs.append("generated_question_for_missing_slot")
                # Use question text as assistant message if message is empty
                if not assistant_message or not assistant_message.strip():
                    assistant_message = q_text
                    repairs.append("assistantMessage_from_question")

    # Check and repair assistantMessage (after question generation)
    if not assistant_message or not assistant_message.strip():
        warnings.append("assistantMessage_empty")
        # Try to use question text if available
        if question and question.text:
            assistant_message = question.text
            repairs.append("assistantMessage_from_question")
        else:
            assistant_message = "I need a bit more information to continue."
            repairs.append("assistantMessage_set_fallback")

    # Metric log for monitoring sanitization rate (scrapable)
    # Format: METRIC sanitization_applied agent=X repairs=N warnings=N
    if repairs:
        logger.info(
            f"METRIC sanitization_applied agent={agent_type} "
            f"repairs={len(repairs)} warnings={len(warnings)} "
            f"conversationId={conversation_id}"
        )

    # Log details if any issues found
    if warnings:
        logger.warning(
            f"Response sanitized [conversationId={conversation_id}, agent={agent_type}]: "
            f"warnings={warnings}, repairs={repairs}"
        )

    # CRITICAL FIX: Always return merged_slots (existing + extracted) to maintain full slot state
    # This ensures the client receives ALL known slots, not just newly extracted ones.
    # Without this, the client sends back stale slots on the next turn, causing slot amnesia.
    #
    # Before fix: extractedData = {"caller_name": "Richard"}  (only new slots)
    # After fix:  extractedData = {"employer_name": "Bunnings", "caller_name": "Richard", ...}  (all slots)

    # Return sanitized response - ALWAYS include merged_slots as extractedData
    return ConversationResponse(
        assistantMessage=assistant_message,
        nextAction=next_action,
        question=question,
        extractedData=merged_slots,  # CRITICAL: Return FULL merged slots, not just new extractions
        confidence=response.confidence,
        confirmationCard=confirmation_card if next_action == NextAction.CONFIRM else None,
        placeSearchParams=place_search_params if next_action == NextAction.FIND_PLACE else None,
        aiCallMade=response.aiCallMade,
        aiModel=response.aiModel
    )


@app.post("/conversation/next", response_model=ConversationResponse)
async def conversation_next(request: ConversationRequest) -> ConversationResponse:
    """
    Process the next turn in a conversation.

    Flow:
    1. If clientAction is CONFIRM/REJECT, handle deterministically (bypass OpenAI)
    2. Otherwise, ALWAYS call OpenAI

    GUARANTEE: This endpoint NEVER returns HTTP 500 due to model output.
    - Invalid JSON from model: parsed, extracted, or repaired
    - Missing fields: filled with defaults or fallback question
    - All failures: logged and return valid ASK_QUESTION response

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
        f"clientAction={request.clientAction}, "
        f"message='{msg_preview}'"
    )

    # TOP-LEVEL EXCEPTION BARRIER: wrap everything to guarantee no 500s from model output
    try:
        # ============================================================
        # IDEMPOTENCY CHECK: prevent duplicate actions (e.g., double-tap confirm)
        # ============================================================
        if request.idempotencyKey:
            cached_response = _get_idempotent_response(request.idempotencyKey)
            if cached_response:
                logger.info(
                    f"METRIC idempotency_hit conversationId={request.conversationId} "
                    f"key={request.idempotencyKey}"
                )
                return cached_response

        # ============================================================
        # DETERMINISTIC CLIENT ACTIONS: bypass OpenAI for CONFIRM/REJECT
        # ============================================================
        if request.clientAction == ClientAction.CONFIRM:
            # User tapped "Yes, call them" - proceed to COMPLETE (or FIND_PLACE if no phone yet)
            logger.info(
                f"METRIC client_action_confirm conversationId={request.conversationId} "
                f"agent={request.agentType.value} "
                f"slots_keys={list(request.slots.keys()) if request.slots else []}"
            )

            # CRITICAL: Preserve all slots in extractedData
            # Without this, Android loses all slot state after CONFIRM
            preserved_slots = request.slots if request.slots else {}

            response = ConversationResponse(
                assistantMessage="Okay — placing the call now.",
                nextAction=NextAction.COMPLETE,
                question=None,
                extractedData=preserved_slots,  # CRITICAL: Preserve all slots
                confidence=Confidence.HIGH,
                confirmationCard=None,
                placeSearchParams=None,
                aiCallMade=False,
                aiModel="deterministic",
            )

            logger.info(
                f"CONFIRM response: extractedData keys={list(preserved_slots.keys())}"
            )

            # Store for idempotency
            if request.idempotencyKey:
                _store_idempotent_response(request.idempotencyKey, response)

            return response

        elif request.clientAction == ClientAction.REJECT:
            # User tapped "Not quite" - ask what needs to be corrected
            logger.info(
                f"METRIC client_action_reject conversationId={request.conversationId} "
                f"agent={request.agentType.value} "
                f"slots_keys={list(request.slots.keys()) if request.slots else []}"
            )

            from .models import Question, InputType

            # CRITICAL: Preserve all slots in extractedData
            # Without this, Android loses all slot state after REJECT
            preserved_slots = request.slots if request.slots else {}

            response = ConversationResponse(
                assistantMessage="No problem! What would you like to change?",
                nextAction=NextAction.ASK_QUESTION,
                question=Question(
                    text="What would you like to change?",
                    field="correction",
                    inputType=InputType.TEXT,
                    choices=None,
                    optional=False,
                ),
                extractedData=preserved_slots,  # CRITICAL: Preserve all slots
                confidence=Confidence.HIGH,
                confirmationCard=None,
                placeSearchParams=None,
                aiCallMade=False,
                aiModel="deterministic",
            )

            logger.info(
                f"REJECT response: extractedData keys={list(preserved_slots.keys())}"
            )

            # Store for idempotency
            if request.idempotencyKey:
                _store_idempotent_response(request.idempotencyKey, response)

            return response

        # ============================================================
        # NORMAL FLOW: Call OpenAI
        # ============================================================
        if openai_service is None:
            raise HTTPException(status_code=503, detail="Service not initialized")

        # Call OpenAI - the service guarantees no exceptions from model output
        response = await openai_service.get_next_turn(
            agent_type=request.agentType,
            user_message=request.userMessage,
            slots=request.slots,
            message_history=request.messageHistory,
            conversation_id=request.conversationId,
        )

        # Sanitize response: validate and auto-repair invalid combinations
        # This now returns merged_slots (existing + extracted) as extractedData
        response = sanitize_conversation_response(
            response,
            request.conversationId,
            request.agentType.value,
            request.slots,
        )

        # Log slot sync warning if client slots are behind merged state
        if response.extractedData and request.slots:
            merged_keys = set(response.extractedData.keys())
            client_keys = set(request.slots.keys())
            new_keys = merged_keys - client_keys
            if new_keys:
                logger.info(
                    f"Slot sync: client missing keys={list(new_keys)}, "
                    f"returning full merged state with {len(merged_keys)} keys "
                    f"conversationId={request.conversationId}"
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
        # FINAL SAFETY NET: if anything unexpected happens, return a safe fallback
        logger.error(
            f"METRIC endpoint_unexpected_error conversationId={request.conversationId} "
            f"agent={request.agentType.value} error={type(e).__name__}",
            exc_info=True
        )
        # Return a safe fallback instead of 500
        return _create_endpoint_fallback_response(
            request.agentType.value,
            request.slots,
            request.conversationId,
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


@app.post("/call/result/format", response_model=CallResultFormatResponseV1)
async def format_call_result(request: CallResultFormatRequestV1) -> CallResultFormatResponseV1:
    """
    Format call results for display in the mobile app.

    Takes raw call data (status, transcript, outcome) and returns
    a user-friendly formatted summary with bullets and next steps.

    Uses OpenAI when transcript or outcome is available.
    Returns deterministic response when both are missing.

    Returns:
        CallResultFormatResponseV1 with formatted title, bullets, facts, next steps

    Errors:
        500: OpenAI formatting failed
    """
    logger.info(f"Call result format request: callId={request.callId}, status={request.status}")

    if call_result_service is None:
        raise HTTPException(
            status_code=500,
            detail="call_result_service_unavailable: Service not initialized"
        )

    try:
        result = await call_result_service.format_call_result(
            agent_type=request.agentType,
            call_id=request.callId,
            status=request.status,
            duration_seconds=request.durationSeconds,
            transcript=request.transcript,
            outcome=request.outcome,
            error=request.error,
            event_transcript=request.eventTranscript,
            business_name=request.businessName,
        )

        return CallResultFormatResponseV1(
            title=result["title"],
            summary=result.get("summary"),
            bullets=result["bullets"],
            extractedFacts=result["extractedFacts"],
            nextSteps=result["nextSteps"],
            formattedTranscript=result.get("formattedTranscript"),
            aiCallMade=result["aiCallMade"],
            aiModel=result["aiModel"],
        )

    except RuntimeError as e:
        logger.error(f"Call result format failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
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


def _is_terminal_text(text: str) -> bool:
    """Check if text indicates the agent is ending the call (goodbye intent).

    Returns True if text contains a goodbye phrase AND no question mark.
    This is a deterministic heuristic to detect terminal responses.

    Handles punctuation variations like:
    - "Thanks for your time. Goodbye!"
    - "Thank you for your time, goodbye."
    - "Goodbye"
    """
    text_lower = text.lower()

    # If there's a question mark, it's not terminal (agent is still asking something)
    if "?" in text:
        return False

    # Normalize text: remove extra punctuation for matching
    # This handles "goodbye!" "goodbye." "goodbye," etc.
    import re
    text_normalized = re.sub(r'[.,!;:\-—]+', ' ', text_lower)
    text_normalized = ' '.join(text_normalized.split())  # Collapse whitespace

    # Check for goodbye phrases (order matters - check specific phrases first)
    goodbye_phrases = [
        # Longer/specific phrases first
        "thank you for your time",
        "thanks for your time",
        "have a great day",
        "have a good day",
        "have a nice day",
        "take care",
        # Short phrases last (to avoid false positives)
        "goodbye",
        "good bye",
        "bye bye",
        "bye",
    ]

    for phrase in goodbye_phrases:
        if phrase in text_normalized:
            return True

    return False




@app.post("/twilio/voice")
async def twilio_voice(
    background_tasks: BackgroundTasks,
    conversationId: str = Query(...)
):
    """
    Twilio voice webhook - called when call connects.

    User speaks FIRST. Opener is pre-warmed in background but NOT spoken
    until after the user's first speech ends and Twilio posts to /twilio/gather.
    """
    voice_received_at = datetime.utcnow()
    logger.info(f"[TIMING] /twilio/voice received at {voice_received_at.isoformat()} for conversationId={conversationId}")

    # Find the call run by conversation_id
    call_run = None
    for run in CALL_RUNS.values():
        if run.conversation_id == conversationId:
            call_run = run
            break

    if call_run:
        # Initialize live conversation state
        call_run.turn = 0
        call_run.retry = 0
        call_run.live_transcript = []

        # Start generating opener if not already ready
        if twilio_service is not None and call_run.pending_agent_reply is None:
            opener_context = f"The callee just answered the phone. Greet them briefly and state why you're calling based on: {call_run.script_preview}"
            background_tasks.add_task(
                twilio_service.generate_agent_response_async,
                call_run.call_id,
                opener_context
            )
            logger.info(f"[TIMING] Pre-warming opener started for call {call_run.call_id}")
        elif call_run.pending_agent_reply is not None:
            logger.info(f"[TIMING] Opener already ready for call {call_run.call_id}, skipping pre-warm")
    else:
        logger.warning(f"twilio_voice: No call run found for conversation {conversationId}")

    webhook_base = os.getenv('WEBHOOK_BASE_URL')

    # Hybrid approach: 1s silent wait, then agent says "Hello?" if no speech
    # This avoids the 10-second Twilio speech detection delay
    # Flow:
    # 1. Call connects → 1s silent wait (first Gather)
    # 2. If user speaks → /twilio/gather fires with their speech
    # 3. If silence after 1s → Agent says "Hello?" → second Gather
    # 4. If still silence → Hang up
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn=0&amp;retry=0"
        method="POST"
        timeout="1"
        speechTimeout="1"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">
    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">Hello?</Say>

    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn=0&amp;retry=1"
        method="POST"
        timeout="5"
        speechTimeout="1"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">
    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">
        I haven't heard anything. Goodbye.
    </Say>
    <Hangup/>
</Response>"""

    twiml_ready_at = datetime.utcnow()
    logger.info(f"[TIMING] /twilio/voice returning TwiML at {twiml_ready_at.isoformat()} (Hybrid: 1s silent wait, then 'Hello?')")

    return Response(content=twiml, media_type="application/xml")


@app.post("/twilio/gather")
async def twilio_gather(
    background_tasks: BackgroundTasks,
    conversationId: str = Query(...),
    turn: int = Query(0),
    retry: int = Query(0),
    SpeechResult: str = Form(""),
):
    """
    Twilio gather webhook - processes speech input and starts async response generation.

    This endpoint uses a filler/poll pattern for natural conversation flow:
    1. When speech received: append to transcript, start background OpenAI task
    2. Return filler TwiML with redirect to /twilio/poll
    3. Poll endpoint checks if response is ready

    Handles:
    - Turn 0: First speech from callee (their greeting)
    - Silence: retry up to 2 times, then hang up
    - Turn limit: after 8 turns, end call politely
    """
    gather_received_at = datetime.utcnow()
    logger.info(f"[TIMING] /twilio/gather received at {gather_received_at.isoformat()} - turn={turn}, retry={retry}, speech='{SpeechResult[:50] if SpeechResult else ''}'")

    webhook_base = os.getenv('WEBHOOK_BASE_URL')

    # Find the call run by conversation_id
    call_run = None
    for run in CALL_RUNS.values():
        if run.conversation_id == conversationId:
            call_run = run
            break

    if not call_run:
        logger.error(f"twilio_gather: No call run found for conversation {conversationId}")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">I'm sorry, something went wrong. Goodbye.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Guard: if call is already terminal (race condition / Twilio retry), just hangup
    if call_run.is_terminal:
        logger.info(f"twilio_gather: Call already terminal, hanging up")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Update call_run state
    call_run.turn = turn
    call_run.retry = retry

    # Handle silence (empty SpeechResult)
    if not SpeechResult or not SpeechResult.strip():
        new_retry = retry + 1
        logger.info(f"Silence detected, retry={new_retry}")

        if new_retry >= 2:
            # Too many silences, hang up
            logger.info(f"Max retries reached, hanging up")
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">I haven't heard anything. Thanks for your time. Goodbye.</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")

        # Re-prompt (different message for turn 0 vs later turns)
        if turn == 0:
            prompt_message = "Hello? Is anyone there?"
        else:
            prompt_message = "I'm sorry, I didn't catch that. Could you please repeat?"

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn={turn}&amp;retry={new_retry}"
        method="POST"
        timeout="6"
        speechTimeout="1"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">

        <Say voice="en-AU-Wavenet-C" language="en-AU">
            {_escape_xml(prompt_message)}
        </Say>

    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">
        I still can't hear you. Thanks for your time. Goodbye.
    </Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Check turn limit
    if turn >= 8:
        logger.info(f"Turn limit reached ({turn}), ending call")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">Thank you so much for your help. I have all the information I need. Have a great day. Goodbye.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Normal turn - process user speech
    user_speech = SpeechResult.strip()

    # Update live transcript with user speech
    call_run.live_transcript.append(f"User: {user_speech}")

    # Check for hold/checking phrases - respond with acknowledgement and wait (don't advance questions)
    # Only triggers for PURE hold phrases (no substantive info like numbers, yes/no, prices)
    if turn > 0 and _is_pure_hold_phrase(user_speech):
        logger.info(f"Hold phrase detected: '{user_speech}', responding with acknowledgement")

        # Update live transcript with acknowledgement
        call_run.live_transcript.append(f"Assistant: {HOLD_ACKNOWLEDGEMENT}")

        # DON'T advance turn - just gather again at same turn
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn={turn}&amp;retry=0"
        method="POST"
        timeout="10"
        speechTimeout="2"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">

        <Say voice="en-AU-Wavenet-C" language="en-AU">
            {_escape_xml(HOLD_ACKNOWLEDGEMENT)}
        </Say>

    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">
        I didn't hear anything. Let me know when you're ready.
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn={turn}&amp;retry=1
    </Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Check if we have a pre-warmed response ready (turn 0 uses pre-warmed opener)
    if turn == 0 and call_run.pending_agent_reply is not None:
        # Pre-warmed opener is ready - deliver it IMMEDIATELY (no filler, no poll)
        agent_response = call_run.pending_agent_reply
        deliver_at = datetime.utcnow()
        logger.info(f"[TIMING] Delivering pre-warmed opener at {deliver_at.isoformat()} for call {call_run.call_id}: {agent_response[:50]}...")

        # Clear pending state
        call_run.pending_agent_reply = None
        call_run.pending_user_speech = None
        call_run.pending_started_at = None

        # Update live transcript
        call_run.live_transcript.append(f"Assistant: {agent_response}")

        # Update turn state
        call_run.turn = 1
        call_run.retry = 0

        # Return Gather TwiML immediately with the opener
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn=1&amp;retry=0"
        method="POST"
        timeout="6"
        speechTimeout="1"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">

        <Say voice="en-AU-Wavenet-C" language="en-AU">
            {_escape_xml(agent_response)}
        </Say>

    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">
        I didn't hear anything.
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn=1&amp;retry=1
    </Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    elif twilio_service is not None:
        # Start async generation in background
        background_tasks.add_task(
            twilio_service.generate_agent_response_async,
            call_run.call_id,
            user_speech
        )
    else:
        logger.error("twilio_gather: twilio_service is None")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">I'm sorry, I'm having technical difficulties. Goodbye.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Select filler phrase based on turn number
    filler = FILLER_PHRASES[turn % len(FILLER_PHRASES)]
    next_turn = turn + 1

    # Return filler TwiML with redirect to poll endpoint (no pause - faster response)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">
        {_escape_xml(filler)}
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/poll?conversationId={conversationId}&amp;turn={next_turn}&amp;attempt=0
    </Redirect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@app.post("/twilio/poll")
async def twilio_poll(
    conversationId: str = Query(...),
    turn: int = Query(1),
    attempt: int = Query(0),
):
    """
    Twilio poll endpoint - checks if async response is ready.

    Polling logic:
    - If pending_agent_reply ready: return normal Gather TwiML with response
    - If not ready and attempt < 3: return filler + pause + redirect to poll with attempt+1
    - If attempt >= 3: return filler + redirect to poll with attempt=0 (reset)
    - Hard cap: if pending_started_at > 20 seconds ago, hang up with apology
    """
    logger.debug(f"Twilio poll: conversationId={conversationId}, turn={turn}, attempt={attempt}")

    webhook_base = os.getenv('WEBHOOK_BASE_URL')

    # Find the call run by conversation_id
    call_run = None
    for run in CALL_RUNS.values():
        if run.conversation_id == conversationId:
            call_run = run
            break

    if not call_run:
        logger.error(f"twilio_poll: No call run found for conversation {conversationId}")
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">I'm sorry, something went wrong. Goodbye.</Say>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Hard timeout check - 20 seconds
    if call_run.pending_started_at:
        elapsed = (datetime.utcnow() - call_run.pending_started_at).total_seconds()
        if elapsed > 20:
            logger.warning(f"Poll timeout exceeded ({elapsed}s) for conversation {conversationId}")
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">I apologize, I'm having technical difficulties. Thank you for your patience. Goodbye.</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")

    # Check if response is ready
    if call_run.pending_agent_reply is not None:
        agent_response = call_run.pending_agent_reply

        # Update live transcript with agent response
        call_run.live_transcript.append(f"Assistant: {agent_response}")

        # Clear pending state
        call_run.pending_agent_reply = None
        call_run.pending_user_speech = None
        call_run.pending_started_at = None

        # Update turn state
        call_run.turn = turn
        call_run.retry = 0

        # Check if this is a terminal response (goodbye)
        is_terminal = _is_terminal_text(agent_response)
        call_run.is_terminal = is_terminal

        if is_terminal:
            # Terminal response - Say goodbye and Hangup immediately (no Gather, no fallback)
            logger.info(f"Poll returning TERMINAL response for turn {turn}: {agent_response[:50]}...")
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">{_escape_xml(agent_response)}</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")

        # Non-terminal response - normal Gather TwiML
        logger.info(f"Poll returning ready response for turn {turn}: {agent_response[:50]}...")

        # Return normal Gather TwiML with the response
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn={turn}&amp;retry=0"
        method="POST"
        timeout="6"
        speechTimeout="1"
        speechModel="phone_call"
        enhanced="true"
        language="en-AU">

        <Say voice="en-AU-Wavenet-C" language="en-AU">
            {_escape_xml(agent_response)}
        </Say>

    </Gather>

    <Say voice="en-AU-Wavenet-C" language="en-AU">
        I didn't hear anything.
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/gather?conversationId={conversationId}&amp;turn={turn}&amp;retry=1
    </Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Response not ready yet - continue polling
    logger.debug(f"Response not ready, attempt={attempt}")

    # Select poll filler based on attempt
    poll_filler = POLL_FILLER_PHRASES[attempt % len(POLL_FILLER_PHRASES)]

    if attempt >= 3:
        # Reset attempt counter
        next_attempt = 0
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">
        {_escape_xml(poll_filler)}
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/poll?conversationId={conversationId}&amp;turn={turn}&amp;attempt={next_attempt}
    </Redirect>
</Response>"""
    else:
        # Return filler + redirect with incremented attempt (no pause - faster)
        next_attempt = attempt + 1
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="en-AU-Wavenet-C" language="en-AU">
        {_escape_xml(poll_filler)}
    </Say>
    <Redirect method="POST">
        {webhook_base}/twilio/poll?conversationId={conversationId}&amp;turn={turn}&amp;attempt={next_attempt}
    </Redirect>
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
