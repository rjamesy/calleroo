"""
Pydantic models for the Conversation API.
Python 3.9 compatible - uses typing.List, typing.Dict, typing.Optional
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    STOCK_CHECKER = "STOCK_CHECKER"
    RESTAURANT_RESERVATION = "RESTAURANT_RESERVATION"
    SICK_CALLER = "SICK_CALLER"
    CANCEL_APPOINTMENT = "CANCEL_APPOINTMENT"


class NextAction(str, Enum):
    ASK_QUESTION = "ASK_QUESTION"
    CONFIRM = "CONFIRM"
    COMPLETE = "COMPLETE"
    FIND_PLACE = "FIND_PLACE"


class InputType(str, Enum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"
    TIME = "TIME"
    BOOLEAN = "BOOLEAN"
    CHOICE = "CHOICE"
    PHONE = "PHONE"
    YES_NO = "YES_NO"  # Added for generic yes/no questions


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class Choice(BaseModel):
    label: str
    value: str


class QuickReply(BaseModel):
    """Universal quick reply for UI chips (replaces choices for consistency)."""
    label: str
    value: str


class Question(BaseModel):
    text: str
    field: str
    inputType: InputType
    choices: Optional[List[Choice]] = None  # Legacy: kept for compatibility
    quickReplies: Optional[List[QuickReply]] = None  # New: unified UI chips
    optional: bool = False


class ConfirmationCard(BaseModel):
    title: str
    lines: List[str]
    confirmLabel: str = "Yes"
    rejectLabel: str = "Not quite"
    cardId: Optional[str] = None  # Stable ID for idempotency (auto-generated if not provided)


class ClientAction(str, Enum):
    """Client-initiated actions that bypass OpenAI."""
    CONFIRM = "CONFIRM"  # User tapped "Yes, call them"
    REJECT = "REJECT"    # User tapped "Not quite"


class ConversationRequest(BaseModel):
    conversationId: str
    agentType: AgentType
    userMessage: str
    slots: Dict[str, Any] = Field(default_factory=dict)
    messageHistory: List[ChatMessage] = Field(default_factory=list)
    debug: bool = False
    # Optional client action for deterministic handling (bypasses OpenAI)
    clientAction: Optional[ClientAction] = None
    # Idempotency key to prevent duplicate actions (e.g., double-tap confirm)
    idempotencyKey: Optional[str] = None
    # Current question slot name (for targeted extraction)
    currentQuestionSlotName: Optional[str] = None


class PlaceSearchParams(BaseModel):
    """Parameters for place search, returned with FIND_PLACE action."""
    query: str
    area: str
    country: str = "AU"


class AgentMeta(BaseModel):
    """Agent metadata for generic UI handling."""
    phoneSource: str  # "PLACE" or "DIRECT_SLOT"
    directPhoneSlot: Optional[str] = None  # Slot name if phoneSource == "DIRECT_SLOT"
    title: str
    description: str


class DebugPayload(BaseModel):
    """Debug information returned when debug=true."""
    planner_action: str
    planner_question_slot: Optional[str] = None
    extraction_llm_used: bool
    extraction_raw_data: Optional[Dict[str, Any]] = None
    merged_slots: Dict[str, Any]
    missing_required_slots: List[str]


class ConversationResponse(BaseModel):
    assistantMessage: str
    nextAction: NextAction
    question: Optional[Question] = None
    extractedData: Optional[Dict[str, Any]] = None
    confidence: Confidence = Confidence.MEDIUM
    confirmationCard: Optional[ConfirmationCard] = None
    placeSearchParams: Optional[PlaceSearchParams] = None
    agentMeta: Optional[AgentMeta] = None  # Agent metadata for generic UI
    aiCallMade: bool
    aiModel: str
    engineVersion: str = "v1"  # "v1" or "v2" - helps debug mixed traffic
    debugPayload: Optional[DebugPayload] = None  # Only present when debug=true


# ============================================================
# Place Search Models (Screen 3 - NO OpenAI, deterministic)
# ============================================================

class PlaceSearchRequest(BaseModel):
    """Request to search for places."""
    query: str
    area: str
    country: str = "AU"
    radius_km: int = 25  # 25, 50, or 100 only


class PlaceCandidate(BaseModel):
    """A place candidate from Google Places API."""
    placeId: str
    name: str
    formattedAddress: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    distanceMeters: Optional[int] = None  # Distance from search center
    hasValidPhone: bool = False  # True only after details confirms valid phone


class PlaceSearchResponse(BaseModel):
    """Response from place search."""
    passNumber: int = 1  # 1=25km, 2=50km, 3=100km
    radiusKm: int
    candidates: List[PlaceCandidate]
    error: Optional[str] = None


class PlaceDetailsRequest(BaseModel):
    """Request for place details."""
    placeId: str
    country: str = "AU"


class PlaceDetailsResponse(BaseModel):
    """Detailed place information with phone number."""
    placeId: str
    name: str
    formattedAddress: Optional[str] = None
    phoneE164: Optional[str] = None  # E.164 format, None if no valid phone
    error: Optional[str] = None  # "NO_PHONE", "PLACE_NOT_FOUND", etc.


# ============================================================
# Geocode Models (standalone geocoding endpoint)
# ============================================================

class GeocodeRequest(BaseModel):
    """Request to geocode an area name."""
    area: str
    country: str = "AU"


class GeocodeResponse(BaseModel):
    """Response from geocoding."""
    latitude: float
    longitude: float
    formattedAddress: str
    error: Optional[str] = None


# ============================================================
# Call Brief Models (Screen 4 - OpenAI generates call script)
# ============================================================

class CallBriefPlace(BaseModel):
    """Place information for call brief."""
    placeId: str
    businessName: str
    formattedAddress: Optional[str] = None
    phoneE164: str


class CallBriefDisclosure(BaseModel):
    """User disclosure settings for the call."""
    nameShare: bool = False
    phoneShare: bool = False


class CallBriefFallbacks(BaseModel):
    """Fallback behaviors during the call (agent-specific)."""
    # Stock Checker fallbacks
    askETA: Optional[bool] = None
    askNearestStore: Optional[bool] = None
    # Restaurant reservation fallbacks
    retryIfNoAnswer: Optional[bool] = None
    retryIfBusy: Optional[bool] = None
    leaveVoicemail: Optional[bool] = None


class CallBriefRequestV2(BaseModel):
    """Request to generate a call brief."""
    conversationId: str
    agentType: str  # "STOCK_CHECKER" or "RESTAURANT_RESERVATION"
    place: CallBriefPlace
    slots: Dict[str, Any] = Field(default_factory=dict)
    disclosure: CallBriefDisclosure = Field(default_factory=CallBriefDisclosure)
    fallbacks: CallBriefFallbacks = Field(default_factory=CallBriefFallbacks)
    debug: bool = False


class CallBriefResponseV2(BaseModel):
    """Response containing the call brief."""
    objective: str  # Short description of call goal
    scriptPreview: str  # Plain text, multi-line, no markdown
    confirmationChecklist: List[str]  # 2-6 items user should verify
    normalizedPhoneE164: str  # Validated/normalized phone
    requiredFieldsMissing: List[str]  # Empty if all required fields present
    aiCallMade: bool
    aiModel: str


# ============================================================
# Call Start Models (Screen 4 - Stub for Step 3)
# ============================================================

class CallStartRequestV2(BaseModel):
    """Request to start a call (stub in Step 3)."""
    conversationId: str
    agentType: str
    placeId: str
    phoneE164: str
    slots: Dict[str, Any] = Field(default_factory=dict)


class CallStartResponseV2(BaseModel):
    """Response from call start (stub in Step 3)."""
    status: str  # "NOT_IMPLEMENTED" in Step 3
    message: str


# ============================================================
# Call Start V3 Models (Step 4 - Real Twilio Calls)
# ============================================================

class CallStartRequestV3(BaseModel):
    """Request to start a real Twilio call."""
    conversationId: str
    agentType: str
    placeId: str
    phoneE164: str
    slots: Dict[str, Any] = Field(default_factory=dict)
    scriptPreview: str  # The generated script to speak


class CallStartResponseV3(BaseModel):
    """Response with real Twilio call ID."""
    callId: str  # Twilio Call SID
    status: str  # "queued", "ringing", etc.
    message: str


class CallStatusResponseV1(BaseModel):
    """Response from GET /call/status/{callId}."""
    callId: str
    status: str  # queued, ringing, in-progress, completed, failed, busy, no-answer
    durationSeconds: Optional[int] = None
    transcript: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None  # OpenAI analysis
    error: Optional[str] = None
    # Call cost (optional - may not be immediately available from Twilio)
    cost: Optional[float] = None
    costCurrency: Optional[str] = None


# ============================================================
# Call Result Format Models (Post-call summary formatting)
# ============================================================

class CallResultFormatRequestV1(BaseModel):
    """Request to format call results for display."""
    agentType: str
    callId: str
    status: str
    durationSeconds: Optional[int] = None
    transcript: Optional[str] = None  # Raw Whisper transcript (fallback)
    eventTranscript: Optional[List[str]] = None  # Event transcript with speaker labels (primary)
    outcome: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    businessName: Optional[str] = None  # Name of business that was called


class CallResultFormatResponseV1(BaseModel):
    """Formatted call results for UI display."""
    title: str  # e.g. "Call completed"
    summary: Optional[str] = None  # 1-2 sentence plain-English summary
    bullets: List[str]  # short bullet points (max 8)
    extractedFacts: Dict[str, Any]  # pass-through from outcome
    nextSteps: List[str]  # 1-4 action items
    formattedTranscript: Optional[str] = None  # Cleaned conversation transcript
    aiCallMade: bool
    aiModel: str
