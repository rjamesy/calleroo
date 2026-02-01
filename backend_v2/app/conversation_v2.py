"""
Generic conversation endpoint using AgentSpec and deterministic planner.

This module provides a new /v2/conversation/next endpoint that:
1. Uses AgentSpec for agent configuration (no per-agent if/else)
2. Uses deterministic planner for flow decisions (LLM is only a parser)
3. Returns quickReplies for universal UI chips
4. Returns agentMeta for client to handle phone routing generically

The existing /conversation/next endpoint is preserved for backwards compatibility.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from fastapi import HTTPException

from .models import (
    ClientAction,
    Confidence,
    ConversationRequest,
    ConversationResponse,
    DebugPayload,
    NextAction,
    Question,
    QuickReply,
    ConfirmationCard,
    PlaceSearchParams,
    AgentMeta,
    InputType,
)
from agents import get_agent_spec, AgentSpec, PhoneSource
from engine.planner import (
    decide_next_action,
    get_missing_required_slots,
    NextAction as PlannerNextAction,
    PlannerResult,
)
from engine.extract import extract_slots, ExtractionResult

logger = logging.getLogger(__name__)


def _log_turn_summary(
    conversation_id: str,
    agent_type: str,
    next_action: str,
    question_slot: Optional[str],
    slots_filled: int,
    ai_call_made: bool,
) -> None:
    """
    6.1 Structured summary log for each conversation turn.

    This provides a single-line summary for monitoring and debugging:
    - conversation_id: Unique conversation identifier
    - agent_type: Which agent handled the request
    - next_action: What the planner decided to do
    - question_slot: Which slot is being asked (if any)
    - slots_filled: Total number of slots collected
    - ai_call_made: Whether LLM was invoked
    """
    logger.info(
        "[V2-SUMMARY] "
        f"id={conversation_id} "
        f"agent={agent_type} "
        f"action={next_action} "
        f"question={question_slot or 'none'} "
        f"slots_filled={slots_filled} "
        f"ai_used={ai_call_made}"
    )


# Idempotency store for preventing duplicate confirmations
# Key: idempotencyKey, Value: (response, timestamp)
_idempotency_store_v2: Dict[str, Tuple[ConversationResponse, datetime]] = {}
_IDEMPOTENCY_TTL = timedelta(minutes=5)


# =============================================================================
# 4.1 Internal Metrics Counters (for anomaly detection, not exposed via API)
# =============================================================================
class _V2Metrics:
    """
    Simple in-memory counters for v2 engine metrics.

    These are for internal monitoring/logging only, not exposed via API.
    In production, these would be exported to Prometheus/DataDog/etc.

    Counters reset on server restart - that's intentional for simplicity.
    """

    def __init__(self):
        self.total_requests = 0
        self.llm_calls = 0
        self.deterministic_only = 0
        self.fallback_used = 0
        self.idempotency_hits = 0
        self.confirm_actions = 0
        self.reject_actions = 0
        self.complete_actions = 0
        self.find_place_actions = 0
        self.ask_question_actions = 0
        # Anomaly detection
        self.consecutive_fallbacks = 0
        self.max_consecutive_fallbacks = 0

    def record_request(self, llm_used: bool, next_action: str, fallback: bool = False):
        """Record metrics for a completed request."""
        self.total_requests += 1

        if llm_used:
            self.llm_calls += 1
        else:
            self.deterministic_only += 1

        if fallback:
            self.fallback_used += 1
            self.consecutive_fallbacks += 1
            self.max_consecutive_fallbacks = max(
                self.max_consecutive_fallbacks,
                self.consecutive_fallbacks
            )
            # Log warning if consecutive fallbacks exceed threshold
            if self.consecutive_fallbacks >= 3:
                logger.warning(
                    f"[V2-ANOMALY] consecutive_fallbacks={self.consecutive_fallbacks} "
                    f"(threshold=3, max_seen={self.max_consecutive_fallbacks})"
                )
        else:
            self.consecutive_fallbacks = 0

        # Track action distribution
        action_upper = next_action.upper() if next_action else ""
        if action_upper == "CONFIRM":
            self.confirm_actions += 1
        elif action_upper == "COMPLETE":
            self.complete_actions += 1
        elif action_upper == "FIND_PLACE":
            self.find_place_actions += 1
        elif action_upper == "ASK_QUESTION":
            self.ask_question_actions += 1
        elif action_upper == "REJECT":
            self.reject_actions += 1

    def record_idempotency_hit(self):
        """Record an idempotency cache hit."""
        self.idempotency_hits += 1

    def log_summary(self):
        """Log a summary of current metrics."""
        if self.total_requests == 0:
            return

        llm_rate = (self.llm_calls / self.total_requests) * 100
        fallback_rate = (self.fallback_used / self.total_requests) * 100

        logger.info(
            f"[V2-METRICS] "
            f"total={self.total_requests} "
            f"llm_rate={llm_rate:.1f}% "
            f"fallback_rate={fallback_rate:.1f}% "
            f"idempotency_hits={self.idempotency_hits} "
            f"actions={{CONFIRM={self.confirm_actions}, "
            f"COMPLETE={self.complete_actions}, "
            f"FIND_PLACE={self.find_place_actions}, "
            f"ASK_QUESTION={self.ask_question_actions}}}"
        )


# Global metrics instance
_metrics = _V2Metrics()


def _get_idempotent_response(key: str) -> Optional[ConversationResponse]:
    """Get cached response for idempotency key if still valid."""
    if key in _idempotency_store_v2:
        response, timestamp = _idempotency_store_v2[key]
        if datetime.now() - timestamp < _IDEMPOTENCY_TTL:
            logger.info(f"Idempotency hit for key={key}")
            return response
        else:
            del _idempotency_store_v2[key]
    return None


def _store_idempotent_response(key: str, response: ConversationResponse) -> None:
    """Store response for idempotency."""
    _idempotency_store_v2[key] = (response, datetime.now())
    # Cleanup old entries
    if len(_idempotency_store_v2) > 1000:
        cutoff = datetime.now() - _IDEMPOTENCY_TTL
        keys_to_remove = [k for k, (_, ts) in _idempotency_store_v2.items() if ts < cutoff]
        for k in keys_to_remove:
            del _idempotency_store_v2[k]


def _build_agent_meta(spec: AgentSpec) -> AgentMeta:
    """Build AgentMeta from AgentSpec."""
    return AgentMeta(
        phoneSource=spec.phone_source.value,
        directPhoneSlot=spec.direct_phone_slot,
        title=spec.title,
        description=spec.description,
    )


def _planner_to_api_question(planner_question) -> Optional[Question]:
    """Convert planner Question to API Question model."""
    if planner_question is None:
        return None

    quick_replies = None
    if planner_question.quick_replies:
        quick_replies = [
            QuickReply(label=qr.label, value=qr.value)
            for qr in planner_question.quick_replies
        ]

    # Map input types
    input_type_map = {
        "TEXT": InputType.TEXT,
        "PHONE": InputType.PHONE,
        "DATE": InputType.DATE,
        "TIME": InputType.TIME,
        "NUMBER": InputType.NUMBER,
        "CHOICE": InputType.CHOICE,
        "YES_NO": InputType.YES_NO,
    }
    input_type = input_type_map.get(planner_question.input_type, InputType.TEXT)

    # Also populate choices for legacy compatibility
    choices = None
    if quick_replies:
        from .models import Choice
        choices = [Choice(label=qr.label, value=qr.value) for qr in quick_replies]

    return Question(
        text=planner_question.prompt,
        field=planner_question.slot_name,
        inputType=input_type,
        choices=choices,
        quickReplies=quick_replies,
        optional=False,
    )


def _planner_to_api_confirmation_card(planner_card) -> Optional[ConfirmationCard]:
    """Convert planner ConfirmationCard to API ConfirmationCard model."""
    if planner_card is None:
        return None

    return ConfirmationCard(
        title=planner_card.title,
        lines=planner_card.lines,
        confirmLabel=planner_card.confirm_label,
        rejectLabel=planner_card.reject_label,
        cardId=planner_card.card_id,
    )


def _planner_to_api_place_search_params(planner_params) -> Optional[PlaceSearchParams]:
    """Convert planner PlaceSearchParams to API PlaceSearchParams model."""
    if planner_params is None:
        return None

    return PlaceSearchParams(
        query=planner_params.query,
        area=planner_params.area,
        country="AU",
    )


def _planner_action_to_api_action(planner_action: PlannerNextAction) -> NextAction:
    """Convert planner NextAction to API NextAction."""
    mapping = {
        PlannerNextAction.ASK_QUESTION: NextAction.ASK_QUESTION,
        PlannerNextAction.CONFIRM: NextAction.CONFIRM,
        PlannerNextAction.COMPLETE: NextAction.COMPLETE,
        PlannerNextAction.FIND_PLACE: NextAction.FIND_PLACE,
    }
    return mapping[planner_action]


async def process_conversation_v2(
    request: ConversationRequest,
    openai_client: Any = None,
    model: str = "gpt-4o-mini",
) -> ConversationResponse:
    """
    Process a conversation turn using the new engine.

    This is the main entry point for the v2 conversation handler.

    Flow:
    1. Check idempotency
    2. Get AgentSpec for the agent type
    3. If clientAction is CONFIRM/REJECT, handle deterministically
    4. Otherwise:
       a. Extract slots from user message (deterministic first, then LLM)
       b. Merge extracted slots with existing slots
       c. Run deterministic planner to decide next action
    5. Build response with agentMeta for generic client handling

    Args:
        request: The conversation request
        openai_client: OpenAI async client for extraction
        model: Model to use for extraction

    Returns:
        ConversationResponse with the next action and data
    """
    msg_preview = request.userMessage[:50] + "..." if len(request.userMessage) > 50 else request.userMessage
    logger.info(
        f"[V2] Conversation turn: id={request.conversationId}, "
        f"agent={request.agentType}, "
        f"clientAction={request.clientAction}, "
        f"currentSlot={request.currentQuestionSlotName}, "
        f"message='{msg_preview}'"
    )

    try:
        # Get AgentSpec
        spec = get_agent_spec(request.agentType.value)
        agent_meta = _build_agent_meta(spec)

        # Idempotency check
        if request.idempotencyKey:
            cached = _get_idempotent_response(request.idempotencyKey)
            if cached:
                logger.info(f"[V2] Idempotency hit: {request.idempotencyKey}")
                _metrics.record_idempotency_hit()
                return cached

        # Get existing slots
        existing_slots = request.slots if request.slots else {}

        # Handle CONFIRM action deterministically
        if request.clientAction == ClientAction.CONFIRM:
            logger.info(f"[V2] Client action: CONFIRM")
            response = ConversationResponse(
                assistantMessage="Great! I'll place the call now.",
                nextAction=NextAction.COMPLETE,
                question=None,
                extractedData=existing_slots,  # Preserve all slots
                confidence=Confidence.HIGH,
                confirmationCard=None,
                placeSearchParams=None,
                agentMeta=agent_meta,  # ALWAYS present
                aiCallMade=False,
                aiModel="deterministic",
                engineVersion="v2",
            )
            if request.idempotencyKey:
                _store_idempotent_response(request.idempotencyKey, response)
            _metrics.record_request(llm_used=False, next_action="COMPLETE")
            return response

        # Handle REJECT action deterministically
        if request.clientAction == ClientAction.REJECT:
            logger.info(f"[V2] Client action: REJECT")
            # Run planner to get next question
            planner_result = decide_next_action(
                spec=spec,
                slots=existing_slots,
                client_action="REJECT",
            )

            response = ConversationResponse(
                assistantMessage=planner_result.assistant_message,
                nextAction=_planner_action_to_api_action(planner_result.next_action),
                question=_planner_to_api_question(planner_result.question),
                extractedData=existing_slots,  # Preserve all slots
                confidence=Confidence.HIGH,
                confirmationCard=None,
                placeSearchParams=None,
                agentMeta=agent_meta,  # ALWAYS present
                aiCallMade=False,
                aiModel="deterministic",
                engineVersion="v2",
            )
            if request.idempotencyKey:
                _store_idempotent_response(request.idempotencyKey, response)
            _metrics.record_request(llm_used=False, next_action=planner_result.next_action.value)
            return response

        # Normal flow: extract slots and run planner

        # Step 1: Extract slots from user message
        extraction_result = await extract_slots(
            spec=spec,
            user_message=request.userMessage,
            current_slot=request.currentQuestionSlotName,
            existing_slots=existing_slots,
            openai_client=openai_client,
            model=model,
        )

        logger.info(
            f"[V2] Extraction: extracted={extraction_result.extracted_data}, "
            f"llm_used={extraction_result.llm_used}"
        )

        # Step 2: Merge extracted slots with existing
        merged_slots = {**existing_slots, **extraction_result.extracted_data}

        # Step 3: Run deterministic planner
        planner_result = decide_next_action(
            spec=spec,
            slots=merged_slots,
            client_action=None,
            user_message=request.userMessage,
            current_question_slot=request.currentQuestionSlotName,
        )

        logger.info(
            f"[V2] Planner: action={planner_result.next_action}, "
            f"question={planner_result.question.slot_name if planner_result.question else None}"
        )

        # Step 4: Build debug payload if requested (6.3)
        debug_payload = None
        if request.debug:
            debug_payload = DebugPayload(
                planner_action=planner_result.next_action.value,
                planner_question_slot=planner_result.question.slot_name if planner_result.question else None,
                extraction_llm_used=extraction_result.llm_used,
                extraction_raw_data=extraction_result.extracted_data,
                merged_slots=merged_slots,
                missing_required_slots=get_missing_required_slots(spec, merged_slots),
            )

        # Step 5: Build response
        response = ConversationResponse(
            assistantMessage=planner_result.assistant_message,
            nextAction=_planner_action_to_api_action(planner_result.next_action),
            question=_planner_to_api_question(planner_result.question),
            extractedData=merged_slots,  # CRITICAL: Return FULL merged slots
            confidence=Confidence.HIGH if not extraction_result.llm_used else Confidence.MEDIUM,
            confirmationCard=_planner_to_api_confirmation_card(planner_result.confirmation_card),
            placeSearchParams=_planner_to_api_place_search_params(planner_result.place_search_params),
            agentMeta=agent_meta,  # ALWAYS present
            aiCallMade=extraction_result.llm_used,
            aiModel=extraction_result.llm_model or "deterministic",
            engineVersion="v2",
            debugPayload=debug_payload,  # Only present when debug=true
        )

        if request.idempotencyKey:
            _store_idempotent_response(request.idempotencyKey, response)

        # 6.1 Structured summary log
        _log_turn_summary(
            conversation_id=request.conversationId,
            agent_type=request.agentType.value,
            next_action=planner_result.next_action.value,
            question_slot=planner_result.question.slot_name if planner_result.question else None,
            slots_filled=len(merged_slots),
            ai_call_made=extraction_result.llm_used,
        )

        # 4.1 Record metrics for monitoring
        _metrics.record_request(
            llm_used=extraction_result.llm_used,
            next_action=planner_result.next_action.value,
        )

        # Log metrics summary every 100 requests
        if _metrics.total_requests % 100 == 0:
            _metrics.log_summary()

        return response

    except ValueError as e:
        # Unknown agent type
        logger.error(f"[V2] Unknown agent type: {request.agentType}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"[V2] Unexpected error: {e}", exc_info=True)
        # Record fallback usage in metrics
        _metrics.record_request(llm_used=False, next_action="ASK_QUESTION", fallback=True)
        # Return a safe fallback
        return _create_fallback_response(request)


def _create_fallback_response(request: ConversationRequest) -> ConversationResponse:
    """Create a safe fallback response when unexpected errors occur."""
    try:
        spec = get_agent_spec(request.agentType.value)
        agent_meta = _build_agent_meta(spec)

        # Find next missing slot
        existing_slots = request.slots if request.slots else {}
        missing = get_missing_required_slots(spec, existing_slots)

        if missing:
            slot_spec = spec.get_slot_by_name(missing[0])
            if slot_spec:
                from backend_v2.engine.planner import build_question
                planner_question = build_question(slot_spec)
                question = _planner_to_api_question(planner_question)

                return ConversationResponse(
                    assistantMessage="I need a bit more information. " + slot_spec.prompt,
                    nextAction=NextAction.ASK_QUESTION,
                    question=question,
                    extractedData=existing_slots,
                    confidence=Confidence.LOW,
                    confirmationCard=None,
                    placeSearchParams=None,
                    agentMeta=agent_meta,  # ALWAYS present
                    aiCallMade=False,
                    aiModel="fallback",
                    engineVersion="v2",
                )

        # All slots filled but error occurred - show confirmation
        from backend_v2.engine.planner import build_confirmation_card
        planner_card = build_confirmation_card(spec, existing_slots)
        confirmation_card = _planner_to_api_confirmation_card(planner_card)

        return ConversationResponse(
            assistantMessage="Let me confirm the details:",
            nextAction=NextAction.CONFIRM,
            question=None,
            extractedData=existing_slots,
            confidence=Confidence.LOW,
            confirmationCard=confirmation_card,
            placeSearchParams=None,
            agentMeta=agent_meta,  # ALWAYS present
            aiCallMade=False,
            aiModel="fallback",
            engineVersion="v2",
        )

    except Exception:
        # Ultimate fallback - still provide minimal agentMeta
        fallback_meta = AgentMeta(
            phoneSource="PLACE",
            directPhoneSlot=None,
            title="Assistant",
            description="",
        )
        return ConversationResponse(
            assistantMessage="I'm sorry, something went wrong. Please try again.",
            nextAction=NextAction.ASK_QUESTION,
            question=Question(
                text="What would you like help with?",
                field="unknown",
                inputType=InputType.TEXT,
            ),
            extractedData=request.slots if request.slots else {},
            confidence=Confidence.LOW,
            confirmationCard=None,
            placeSearchParams=None,
            agentMeta=fallback_meta,  # ALWAYS present (even in ultimate fallback)
            aiCallMade=False,
            aiModel="fallback",
            engineVersion="v2",
        )
