"""
OpenAI service for conversation management.

DEPRECATED: This service is used by the legacy /conversation/next endpoint.
The new /v2/conversation/next endpoint uses:
- AgentSpec registry (agents/specs.py) for slot definitions
- Deterministic planner (engine/planner.py) for flow control
- LLM only for slot extraction (engine/extract.py), not flow decisions

This service is preserved for:
- Kill switch fallback (CONVERSATION_ENGINE_KILL_SWITCH=true)
- Backwards compatibility during migration

RESILIENCE DESIGN:
- NEVER returns 500 due to model output
- Multi-stage parsing: raw JSON → extract from text → repair retry
- Deterministic fallback to ASK_QUESTION on any failure
- Comprehensive logging with conversationId for debugging

Python 3.9 compatible - uses typing.Dict, typing.List, typing.Optional
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from .models import (
    AgentType,
    ChatMessage,
    Choice,
    Confidence,
    ConfirmationCard,
    ConversationResponse,
    InputType,
    NextAction,
    PlaceSearchParams,
    Question,
)
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)

# Maximum chars to log from OpenAI response on error
MAX_ERROR_LOG_CHARS = 2000

# Required slots per agent type for fallback question generation
REQUIRED_SLOTS: Dict[str, List[Tuple[str, str, str]]] = {
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

# All known slot keys per agent type (for detecting slot-only responses)
KNOWN_SLOT_KEYS: Dict[str, set] = {
    "SICK_CALLER": {
        "employer_name", "employer_phone", "caller_name", "shift_date",
        "shift_start_time", "reason_category", "expected_return_date", "note_for_team"
    },
    "STOCK_CHECKER": {
        "retailer_name", "product_name", "quantity", "store_location",
        "brand", "model", "variant"
    },
    "RESTAURANT_RESERVATION": {
        "restaurant_name", "party_size", "date", "time",
        "suburb_or_area", "share_contact"
    },
    "CANCEL_APPOINTMENT": {
        "business_name", "appointment_day", "appointment_time", "customer_name",
        "business_location", "reason_enabled", "cancel_reason", "booking_reference",
        "reschedule_intent"
    },
}

# Standard response fields that indicate a proper response structure
RESPONSE_STRUCTURE_KEYS = {
    "assistantMessage", "nextAction", "question", "extractedData",
    "confidence", "confirmationCard", "placeSearchParams"
}

# Common invalid keys that models sometimes use instead of proper field names
INVALID_SLOT_KEYS = {"slot", "value", "answer", "response", "data", "input"}


def _get_last_question_field(message_history: List[Any]) -> Optional[str]:
    """
    Extract the last question.field from message history.
    Used to repair invalid slot keys like "slot" -> actual field name.
    """
    # Walk backwards through history looking for assistant messages
    for msg in reversed(message_history):
        if hasattr(msg, 'role') and msg.role == 'assistant':
            content = msg.content
            # Try to parse as JSON to find question.field
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'question' in data:
                    q = data.get('question')
                    if isinstance(q, dict) and 'field' in q:
                        return q['field']
            except (json.JSONDecodeError, TypeError):
                pass
    return None


class OpenAIService:
    """Service for calling OpenAI to drive conversation flow.

    GUARANTEE: get_next_turn() NEVER raises exceptions from model output.
    All parsing failures result in a valid fallback response.
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required")

        self.client = AsyncOpenAI(api_key=api_key)
        # Default to gpt-4o-mini for cost/speed balance
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        logger.info(f"OpenAI service configured with model: {self.model}")

    async def get_next_turn(
        self,
        agent_type: AgentType,
        user_message: str,
        slots: Dict[str, Any],
        message_history: List[ChatMessage],
        conversation_id: str = "unknown",
    ) -> ConversationResponse:
        """
        Call OpenAI to determine the next turn in the conversation.

        GUARANTEE: This method NEVER raises exceptions due to model output.
        - If model returns invalid JSON: attempts extraction and repair
        - If repair fails: returns fallback ASK_QUESTION response
        - All failures are logged with conversationId for debugging

        This method ALWAYS calls OpenAI - no caching, no local heuristics.
        OpenAI is the sole authority for conversation flow.
        """
        try:
            return await self._get_next_turn_impl(
                agent_type, user_message, slots, message_history, conversation_id
            )
        except Exception as e:
            # TOP-LEVEL EXCEPTION BARRIER
            # This should never happen, but if it does, return a safe fallback
            logger.error(
                f"METRIC model_unexpected_error agent={agent_type.value} "
                f"error={type(e).__name__} conversationId={conversation_id}",
                exc_info=True
            )
            return self._create_fallback_response(
                agent_type.value, slots, self.model,
                reason="unexpected_exception"
            )

    async def _get_next_turn_impl(
        self,
        agent_type: AgentType,
        user_message: str,
        slots: Dict[str, Any],
        message_history: List[ChatMessage],
        conversation_id: str,
    ) -> ConversationResponse:
        """Internal implementation of get_next_turn with full error handling."""
        system_prompt = get_system_prompt(agent_type.value)

        # Build context message with current slots
        context = self._build_context(slots, message_history)

        # Build messages for OpenAI
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": context},
        ]

        # Add message history
        for msg in message_history:
            messages.append({"role": msg.role, "content": msg.content})

        # Add current user message if not empty (empty = start of conversation)
        if user_message:
            messages.append({"role": "user", "content": user_message})
        else:
            # Starting conversation - ask OpenAI to begin
            messages.append({
                "role": "user",
                "content": "[START_CONVERSATION] Please greet the user and ask the first question."
            })

        logger.info(f"Calling OpenAI ({self.model}) with {len(messages)} messages")

        # STAGE 1: Call OpenAI
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,  # Low temperature for consistent JSON output
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content
        except Exception as e:
            logger.error(
                f"METRIC model_api_error agent={agent_type.value} "
                f"error={type(e).__name__} conversationId={conversation_id}"
            )
            return self._create_fallback_response(
                agent_type.value, slots, self.model,
                reason="openai_api_error"
            )

        logger.debug(f"OpenAI raw response: {raw_content[:500] if raw_content else 'None'}...")

        # STAGE 2: Parse response (with extraction and retry)
        parsed = await self._parse_with_retry(
            raw_content, agent_type, slots, messages, conversation_id, message_history
        )

        return parsed

    async def _parse_with_retry(
        self,
        raw_content: Optional[str],
        agent_type: AgentType,
        slots: Dict[str, Any],
        original_messages: List[Dict[str, str]],
        conversation_id: str,
        message_history: List[ChatMessage] = None,
    ) -> ConversationResponse:
        """
        Multi-stage parsing with retry:
        1. Try direct JSON parse
        2. Try extracting JSON from text
        3. Retry with repair prompt
        4. Return fallback
        """
        if message_history is None:
            message_history = []

        # STAGE 2a: Try direct parse
        result, error = self._try_parse_json(
            raw_content, agent_type.value, conversation_id, "raw", slots, message_history
        )
        if result is not None:
            return result

        # STAGE 2b: Try extracting JSON object from text
        extracted_json = self._extract_json_from_text(raw_content)
        if extracted_json:
            result, error = self._try_parse_json(
                extracted_json, agent_type.value, conversation_id, "extract", slots, message_history
            )
            if result is not None:
                logger.info(
                    f"METRIC model_parse_recovered agent={agent_type.value} "
                    f"stage=extract conversationId={conversation_id}"
                )
                return result

        # STAGE 2c: Retry with repair prompt
        logger.warning(
            f"Attempting repair retry for conversationId={conversation_id}, "
            f"agent={agent_type.value}"
        )

        repair_result = await self._retry_with_repair_prompt(
            original_messages, agent_type, slots, conversation_id, message_history
        )
        if repair_result is not None:
            logger.info(
                f"METRIC model_parse_recovered agent={agent_type.value} "
                f"stage=retry conversationId={conversation_id}"
            )
            return repair_result

        # STAGE 2d: All attempts failed - return deterministic fallback
        logger.error(
            f"METRIC model_parse_failed agent={agent_type.value} "
            f"stage=all_attempts conversationId={conversation_id}"
        )
        return self._create_fallback_response(
            agent_type.value, slots, self.model,
            reason="parse_failed_after_retry"
        )

    def _try_parse_json(
        self,
        content: Optional[str],
        agent_type: str,
        conversation_id: str,
        stage: str,
        existing_slots: Dict[str, Any] = None,
        message_history: List[ChatMessage] = None,
    ) -> Tuple[Optional[ConversationResponse], Optional[str]]:
        """
        Try to parse content as JSON and convert to ConversationResponse.
        Returns (response, None) on success or (None, error_message) on failure.

        Special handling for slot-only responses:
        If the model returns valid JSON containing only known slot keys (no
        assistantMessage/nextAction), treat it as extractedData and build
        a valid ASK_QUESTION response for the next missing slot.

        Args:
            existing_slots: Already collected slots (used to determine next question)
            message_history: Previous messages (used to determine last question field)
        """
        if existing_slots is None:
            existing_slots = {}
        if message_history is None:
            message_history = []

        # Determine last question field for repairing invalid keys like "slot"
        last_question_field = _get_last_question_field(message_history)

        if not content:
            return None, "empty_content"

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            truncated = content[:MAX_ERROR_LOG_CHARS] if len(content) > MAX_ERROR_LOG_CHARS else content
            logger.warning(
                f"METRIC model_parse_failed agent={agent_type} stage={stage} "
                f"error=JSONDecodeError conversationId={conversation_id} "
                f"raw={truncated}"
            )
            return None, f"json_decode_error: {str(e)}"

        # Check if this is a slot-only response (no response structure keys present)
        data_keys = set(data.keys())
        has_response_structure = bool(data_keys & RESPONSE_STRUCTURE_KEYS)
        known_slots = KNOWN_SLOT_KEYS.get(agent_type, set())
        has_known_slots = bool(data_keys & known_slots)
        is_slot_only = not has_response_structure and has_known_slots

        # Debug logging for slot detection
        if not has_response_structure and not has_known_slots:
            logger.debug(
                f"Response has unknown structure: keys={list(data_keys)} "
                f"conversationId={conversation_id}"
            )

        if is_slot_only:
            # This is a slot-only response - treat as extractedData
            # Only include slots that are NEW (not already in existing_slots)
            extracted_slots = {k: v for k, v in data.items() if k in known_slots}
            new_slots = {k: v for k, v in extracted_slots.items()
                        if k not in existing_slots or existing_slots.get(k) != v}

            if new_slots:
                logger.info(
                    f"METRIC model_slot_only_response agent={agent_type} "
                    f"new_slots={list(new_slots.keys())} conversationId={conversation_id}"
                )
                # Merge with existing slots to determine next question
                all_slots = {**existing_slots, **new_slots}
                # Build a response with the extracted data (only new slots)
                return self._build_slot_only_response(
                    new_slots, agent_type, self.model, all_slots
                ), None
            else:
                # No new slots extracted - this is effectively a parse failure
                # Fall through to try building with defaults
                logger.info(
                    f"METRIC model_slot_echo_only agent={agent_type} "
                    f"echoed_slots={list(extracted_slots.keys())} conversationId={conversation_id}"
                )

        # Check for required fields and log if missing
        missing_fields = []
        if "assistantMessage" not in data or not data.get("assistantMessage"):
            missing_fields.append("assistantMessage")
        if "nextAction" not in data:
            missing_fields.append("nextAction")

        if missing_fields:
            truncated = json.dumps(data)[:MAX_ERROR_LOG_CHARS]
            logger.info(
                f"METRIC model_response_incomplete agent={agent_type} stage={stage} "
                f"missing={missing_fields} conversationId={conversation_id}"
            )
            # Don't fail - try to build response anyway with defaults

        # Build response with defensive defaults
        try:
            return self._build_response_from_data(
                data,
                self.model,
                agent_type=agent_type,
                last_question_field=last_question_field,
                existing_slots=existing_slots,
                conversation_id=conversation_id,
            ), None
        except Exception as e:
            logger.warning(
                f"METRIC model_parse_failed agent={agent_type} stage={stage} "
                f"error={type(e).__name__} conversationId={conversation_id}"
            )
            return None, f"build_error: {str(e)}"

    def _build_slot_only_response(
        self,
        extracted_slots: Dict[str, Any],
        agent_type: str,
        model: str,
        all_slots: Dict[str, Any] = None,
    ) -> ConversationResponse:
        """
        Build a valid response from a slot-only JSON response.

        When the model returns just extracted slots (e.g., {"shift_date": "2026-02-01"}),
        we treat this as successful extraction and generate a question for the next
        missing required slot.

        Args:
            extracted_slots: The newly extracted slots from this response
            all_slots: All slots (existing + newly extracted) for determining next question
        """
        if all_slots is None:
            all_slots = extracted_slots

        # Find the next missing required slot (considering ALL slots)
        required = REQUIRED_SLOTS.get(agent_type, [])
        next_slot = None

        for field, question_text, input_type in required:
            if field not in all_slots or not all_slots.get(field):
                next_slot = (field, question_text, input_type)
                break

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
                choices=self._get_choices_for_field(agent_type, field),
                optional=False,
            )
            assistant_message = f"Got it. {question_text}"
        else:
            # All required slots present - this shouldn't happen but handle gracefully
            question = None
            assistant_message = "I have all the information I need."

        return ConversationResponse(
            assistantMessage=assistant_message,
            nextAction=NextAction.ASK_QUESTION,
            question=question,
            extractedData=extracted_slots,
            confidence=Confidence.HIGH,  # High confidence since we successfully extracted
            confirmationCard=None,
            placeSearchParams=None,
            aiCallMade=True,
            aiModel=model,
        )

    def _extract_json_from_text(self, content: Optional[str]) -> Optional[str]:
        """
        Try to extract a JSON object from text that may contain other content.
        Handles cases where model outputs markdown or explanatory text.
        """
        if not content:
            return None

        # Try to find JSON object in the text
        # Look for {...} pattern, handling nested braces
        patterns = [
            r'```json\s*(\{.*?\})\s*```',  # Markdown code block
            r'```\s*(\{.*?\})\s*```',       # Generic code block
            r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',  # Nested braces pattern
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    json.loads(match)
                    return match
                except json.JSONDecodeError:
                    continue

        # Last resort: find first { and last } and try that
        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            candidate = content[first_brace:last_brace + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        return None

    async def _retry_with_repair_prompt(
        self,
        original_messages: List[Dict[str, str]],
        agent_type: AgentType,
        slots: Dict[str, Any],
        conversation_id: str,
        message_history: List[ChatMessage] = None,
    ) -> Optional[ConversationResponse]:
        """
        Retry the OpenAI call with a repair prompt that emphasizes JSON-only output.
        Returns None if retry also fails.
        """
        repair_prompt = """CRITICAL: Your previous response was not valid JSON.

Output ONLY a valid JSON object with this exact structure:
{
  "assistantMessage": "Your message to the user (REQUIRED - non-empty string)",
  "nextAction": "ASK_QUESTION",
  "question": {"text": "Question text", "field": "field_name", "inputType": "TEXT", "optional": false},
  "extractedData": {},
  "confidence": "MEDIUM"
}

RULES:
- Output ONLY the JSON object, nothing else
- No markdown, no backticks, no explanation
- assistantMessage MUST be a non-empty string
- nextAction MUST be one of: ASK_QUESTION, CONFIRM, COMPLETE, FIND_PLACE
"""

        messages = original_messages + [
            {"role": "assistant", "content": "(invalid response)"},
            {"role": "user", "content": repair_prompt},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,  # Zero temperature for maximum consistency
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            retry_content = response.choices[0].message.content

            result, _ = self._try_parse_json(
                retry_content, agent_type.value, conversation_id, "retry", slots,
                message_history if message_history else []
            )
            return result

        except Exception as e:
            logger.error(
                f"METRIC model_retry_error agent={agent_type.value} "
                f"error={type(e).__name__} conversationId={conversation_id}"
            )
            return None

    def _sanitize_extracted_data(
        self,
        extracted_data: Optional[Dict[str, Any]],
        agent_type: str,
        last_question_field: Optional[str],
        existing_slots: Dict[str, Any],
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Sanitize and repair extractedData from model response.

        Fixes:
        1. Removes keys not in KNOWN_SLOT_KEYS
        2. Repairs invalid keys like "slot" -> last_question_field
        3. Preserves existing slots that would be lost

        Returns sanitized extractedData or None.
        """
        if not extracted_data or not isinstance(extracted_data, dict):
            return None

        known_slots = KNOWN_SLOT_KEYS.get(agent_type, set())
        sanitized: Dict[str, Any] = {}

        for key, value in extracted_data.items():
            # Skip empty values
            if value is None or value == "":
                continue

            if key in known_slots:
                # Valid key - keep it
                sanitized[key] = value
            elif key in INVALID_SLOT_KEYS:
                # Invalid key (e.g., "slot") - try to repair
                if last_question_field and last_question_field in known_slots:
                    logger.warning(
                        f"METRIC extracted_key_repaired agent={agent_type} "
                        f"from={key} to={last_question_field} value={value} "
                        f"conversationId={conversation_id}"
                    )
                    sanitized[last_question_field] = value
                else:
                    logger.warning(
                        f"METRIC extracted_key_invalid agent={agent_type} "
                        f"key={key} value={value} no_repair_target "
                        f"conversationId={conversation_id}"
                    )
            else:
                # Unknown key - log and drop
                logger.info(
                    f"METRIC extracted_key_dropped agent={agent_type} "
                    f"key={key} conversationId={conversation_id}"
                )

        # Safety check: don't lose existing required slots
        required_fields = [f for f, _, _ in REQUIRED_SLOTS.get(agent_type, [])]
        for field in required_fields:
            if field in existing_slots and field not in sanitized:
                # Slot existed before but not in new extraction - preserve it
                # (This prevents regression where model forgets slots)
                pass  # We don't add it to extractedData, but existing_slots is preserved by caller

        if not sanitized:
            return None

        return sanitized

    def _build_response_from_data(
        self,
        data: Dict[str, Any],
        model: str,
        agent_type: str = "UNKNOWN",
        last_question_field: Optional[str] = None,
        existing_slots: Dict[str, Any] = None,
        conversation_id: str = "unknown",
    ) -> ConversationResponse:
        """
        Build ConversationResponse from parsed JSON data.
        Uses defensive defaults for all optional fields.
        Sanitizes extractedData to ensure only valid slot keys are included.
        """
        if existing_slots is None:
            existing_slots = {}

        # Get assistant message with fallback
        assistant_message = data.get("assistantMessage", "")
        if not assistant_message or not str(assistant_message).strip():
            assistant_message = "I'm processing your request. Could you tell me more?"

        # Parse nextAction with fallback
        try:
            next_action = NextAction(data.get("nextAction", "ASK_QUESTION"))
        except ValueError:
            next_action = NextAction.ASK_QUESTION

        # Parse question if present
        question: Optional[Question] = None
        if data.get("question"):
            try:
                q = data["question"]
                choices: Optional[List[Choice]] = None
                if q.get("choices"):
                    choices = [
                        Choice(
                            label=c.get("label", ""),
                            value=c.get("value", c.get("label", ""))
                        )
                        for c in q["choices"]
                        if isinstance(c, dict)
                    ]

                # Parse inputType with fallback
                try:
                    input_type = InputType(q.get("inputType", "TEXT"))
                except ValueError:
                    input_type = InputType.TEXT

                question = Question(
                    text=q.get("text", ""),
                    field=q.get("field", "unknown"),
                    inputType=input_type,
                    choices=choices,
                    optional=q.get("optional", False),
                )
            except Exception:
                # If question parsing fails, leave it as None
                pass

        # Parse confirmation card if present
        confirmation_card: Optional[ConfirmationCard] = None
        if data.get("confirmationCard"):
            try:
                cc = data["confirmationCard"]
                title = cc.get("title", "Confirmation")
                lines = cc.get("lines", []) if isinstance(cc.get("lines"), list) else []
                # Generate stable cardId from content hash
                card_content = f"{title}|{'|'.join(lines)}"
                card_id = hex(hash(card_content) & 0xFFFFFFFF)[2:]  # Positive hash as hex
                confirmation_card = ConfirmationCard(
                    title=title,
                    lines=lines,
                    confirmLabel=cc.get("confirmLabel", "Yes"),
                    rejectLabel=cc.get("rejectLabel", "Not quite"),
                    cardId=card_id,
                )
            except Exception:
                pass

        # Parse placeSearchParams if present
        place_search_params: Optional[PlaceSearchParams] = None
        if data.get("placeSearchParams"):
            try:
                psp = data["placeSearchParams"]
                place_search_params = PlaceSearchParams(
                    query=psp.get("query", ""),
                    area=psp.get("area", ""),
                )
            except Exception:
                pass

        # Parse confidence with fallback
        try:
            confidence = Confidence(data.get("confidence", "MEDIUM"))
        except ValueError:
            confidence = Confidence.MEDIUM

        # Sanitize extractedData - fix invalid keys like "slot" -> actual field
        raw_extracted = data.get("extractedData") if isinstance(data.get("extractedData"), dict) else None
        sanitized_extracted = self._sanitize_extracted_data(
            raw_extracted,
            agent_type,
            last_question_field,
            existing_slots,
            conversation_id,
        )

        return ConversationResponse(
            assistantMessage=assistant_message,
            nextAction=next_action,
            question=question,
            extractedData=sanitized_extracted,
            confidence=confidence,
            confirmationCard=confirmation_card,
            placeSearchParams=place_search_params,
            aiCallMade=True,
            aiModel=model,
        )

    def _create_fallback_response(
        self,
        agent_type: str,
        slots: Dict[str, Any],
        model: str,
        reason: str,
    ) -> ConversationResponse:
        """
        Create a deterministic fallback ASK_QUESTION response.
        Finds the next missing required slot for the agent type.
        """
        # Find the next missing required slot
        required = REQUIRED_SLOTS.get(agent_type, [])

        next_slot = None
        for field, question_text, input_type in required:
            if field not in slots or not slots.get(field):
                next_slot = (field, question_text, input_type)
                break

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
                choices=self._get_choices_for_field(agent_type, field),
                optional=False,
            )
            assistant_message = question_text
        else:
            # All required slots present but still failed - generic fallback
            question = Question(
                text="Could you please provide more details?",
                field="additional_info",
                inputType=InputType.TEXT,
                choices=None,
                optional=True,
            )
            assistant_message = "I need a bit more information to continue. Could you please provide more details?"

        logger.info(
            f"Created fallback response for agent={agent_type} reason={reason} "
            f"next_field={question.field}"
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
            aiModel=model,
        )

    def _get_choices_for_field(
        self,
        agent_type: str,
        field: str,
    ) -> Optional[List[Choice]]:
        """Get predefined choices for specific fields."""
        if agent_type == "SICK_CALLER" and field == "reason_category":
            return [
                Choice(label="I'm sick", value="SICK"),
                Choice(label="Caring for someone", value="CARER"),
                Choice(label="Mental health day", value="MENTAL_HEALTH"),
                Choice(label="Medical appointment", value="MEDICAL_APPOINTMENT"),
                Choice(label="Other", value="OTHER"),
            ]
        return None

    def _build_context(
        self,
        slots: Dict[str, Any],
        message_history: List[ChatMessage]
    ) -> str:
        """Build a context message with current slots and date anchors for OpenAI."""
        from datetime import datetime
        import pytz

        # Get current date/time in Australian timezone for relative date resolution
        try:
            tz = pytz.timezone("Australia/Brisbane")
            now = datetime.now(tz)
        except Exception:
            now = datetime.now()

        context_parts = [
            "CURRENT STATE:",
            f"CURRENT_DATE_ISO: {now.strftime('%Y-%m-%d')}",
            f"CURRENT_TIME: {now.strftime('%H:%M')}",
            f"TIMEZONE: Australia/Brisbane",
            f"DAY_OF_WEEK: {now.strftime('%A')}",
        ]

        # Add explicit date examples for "today" and "tomorrow"
        tomorrow = now + __import__('datetime').timedelta(days=1)
        context_parts.append(f"'today' = {now.strftime('%Y-%m-%d')}")
        context_parts.append(f"'tomorrow' = {tomorrow.strftime('%Y-%m-%d')}")

        if slots:
            context_parts.append(f"Collected slots: {json.dumps(slots)}")
        else:
            context_parts.append("Collected slots: (none yet)")

        context_parts.append(f"Message count: {len(message_history)}")

        return "\n".join(context_parts)
