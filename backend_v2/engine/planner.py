"""
Deterministic conversation planner.

This module is the SINGLE SOURCE OF TRUTH for conversation flow decisions.
It uses AgentSpec to determine:
- Which slot to ask for next
- When to show confirmation
- When the conversation is complete
- When to trigger place search

NO LLM calls are made in this module. All logic is deterministic.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List
import logging
import re

from agents.specs import AgentSpec, SlotSpec, InputType, PhoneSource

logger = logging.getLogger(__name__)


class NextAction(str, Enum):
    """Possible next actions in the conversation flow."""
    ASK_QUESTION = "ASK_QUESTION"
    CONFIRM = "CONFIRM"
    COMPLETE = "COMPLETE"
    FIND_PLACE = "FIND_PLACE"


class ClientAction(str, Enum):
    """Actions the client can send to influence flow."""
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"


@dataclass
class QuickReply:
    """A quick reply option for the UI."""
    label: str
    value: str


@dataclass
class Question:
    """A question to ask the user."""
    slot_name: str
    input_type: str
    prompt: str
    quick_replies: Optional[List[QuickReply]] = None


@dataclass
class ConfirmationCard:
    """A confirmation card to show the user."""
    title: str
    lines: List[str]
    confirm_label: str = "Yes, that's correct"
    reject_label: str = "No, let me change something"
    card_id: Optional[str] = None


@dataclass
class PlaceSearchParams:
    """Parameters for triggering a place search."""
    query: str
    area: str


@dataclass
class PlannerResult:
    """Result of the planner decision."""
    next_action: NextAction
    question: Optional[Question] = None
    confirmation_card: Optional[ConfirmationCard] = None
    place_search_params: Optional[PlaceSearchParams] = None
    assistant_message: str = ""


# =============================================================================
# SLOT VALUE CHECKING
# =============================================================================

def is_slot_filled(slots: Dict[str, Any], slot_name: str) -> bool:
    """
    Check if a slot has a valid (non-empty) value.

    A slot is considered filled if:
    - It exists in the slots dict
    - Its value is not None
    - Its value is not an empty string
    - Its value is not 0 (for number slots, 0 might be valid, but we treat it as unfilled)
    """
    value = slots.get(slot_name)
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    # Note: 0 is treated as filled for numbers (quantity=0 is valid)
    return True


def get_next_slot(spec: AgentSpec, slots: Dict[str, Any]) -> Optional[SlotSpec]:
    """
    Get the next slot that needs to be filled.

    Returns the first required slot that is not yet filled, in order.
    If all required slots are filled, returns None.

    Args:
        spec: The agent specification
        slots: Current slot values

    Returns:
        The next SlotSpec to ask for, or None if all required slots are filled
    """
    for slot_spec in spec.slots_in_order:
        if slot_spec.required and not is_slot_filled(slots, slot_spec.name):
            return slot_spec
    return None


def get_missing_required_slots(spec: AgentSpec, slots: Dict[str, Any]) -> List[str]:
    """
    Get list of required slot names that are missing.

    Args:
        spec: The agent specification
        slots: Current slot values

    Returns:
        List of missing required slot names
    """
    missing = []
    for slot_spec in spec.slots_in_order:
        if slot_spec.required and not is_slot_filled(slots, slot_spec.name):
            missing.append(slot_spec.name)
    return missing


# =============================================================================
# FIND_PLACE DETECTION
# =============================================================================

# Keywords that indicate user doesn't know the phone number
FIND_PLACE_KEYWORDS = [
    "don't know",
    "dont know",
    "not sure",
    "find it",
    "look it up",
    "search for it",
    "i don't have",
    "i dont have",
    "can you find",
    "help me find",
    "find the number",
    "look up the number",
    "search",
    "find",
]


def should_trigger_find_place(
    user_message: str,
    current_slot: Optional[SlotSpec],
) -> bool:
    """
    Check if the user message indicates they want to search for a phone number.

    This is only relevant when:
    - We're asking for a PHONE slot
    - User indicates they don't know the number

    Args:
        user_message: The user's message
        current_slot: The slot we're currently asking for

    Returns:
        True if we should trigger FIND_PLACE action
    """
    if current_slot is None:
        return False

    if current_slot.input_type != InputType.PHONE:
        return False

    message_lower = user_message.lower()
    for keyword in FIND_PLACE_KEYWORDS:
        if keyword in message_lower:
            return True

    return False


# =============================================================================
# QUESTION BUILDING
# =============================================================================

def build_question(slot_spec: SlotSpec) -> Question:
    """
    Build a Question object from a SlotSpec.

    Args:
        slot_spec: The slot specification

    Returns:
        A Question object ready for the response
    """
    quick_replies = None
    qr_data = slot_spec.get_quick_replies()
    if qr_data:
        quick_replies = [QuickReply(label=qr["label"], value=qr["value"]) for qr in qr_data]

    return Question(
        slot_name=slot_spec.name,
        input_type=slot_spec.input_type.value,
        prompt=slot_spec.prompt,
        quick_replies=quick_replies,
    )


# =============================================================================
# CONFIRMATION CARD BUILDING
# =============================================================================

def format_slot_value_for_display(slot_name: str, value: Any) -> str:
    """
    Format a slot value for display in confirmation card.

    Args:
        slot_name: The slot name
        value: The slot value

    Returns:
        Formatted string for display
    """
    if value is None:
        return "(not provided)"

    value_str = str(value)

    # Map reason codes to human-readable labels
    reason_mapping = {
        "SICK": "I'm sick",
        "CARER": "Caring for someone",
        "MENTAL_HEALTH": "Mental health day",
        "MEDICAL_APPOINTMENT": "Medical appointment",
    }

    if slot_name == "reason_category" and value_str in reason_mapping:
        return reason_mapping[value_str]

    return value_str


def build_confirmation_card(spec: AgentSpec, slots: Dict[str, Any]) -> ConfirmationCard:
    """
    Build a confirmation card from the AgentSpec template and current slots.

    Args:
        spec: The agent specification
        slots: Current slot values

    Returns:
        A ConfirmationCard object ready for the response
    """
    # Format each line by substituting slot values
    formatted_lines = []
    for line_template in spec.confirm_lines:
        formatted_line = line_template
        # Find all {slot_name} placeholders and replace them
        placeholders = re.findall(r'\{(\w+)\}', line_template)
        for placeholder in placeholders:
            value = slots.get(placeholder, "(not provided)")
            display_value = format_slot_value_for_display(placeholder, value)
            formatted_line = formatted_line.replace(f"{{{placeholder}}}", display_value)
        formatted_lines.append(formatted_line)

    # Generate stable card ID from content hash
    card_content = f"{spec.confirm_title}|{'|'.join(formatted_lines)}"
    card_id = hex(hash(card_content) & 0xFFFFFFFF)[2:]

    return ConfirmationCard(
        title=spec.confirm_title,
        lines=formatted_lines,
        confirm_label="Yes, that's correct",
        reject_label="No, let me change something",
        card_id=card_id,
    )


# =============================================================================
# PLACE SEARCH PARAMS BUILDING
# =============================================================================

def build_place_search_params(spec: AgentSpec, slots: Dict[str, Any]) -> PlaceSearchParams:
    """
    Build place search parameters from the AgentSpec and current slots.

    Args:
        spec: The agent specification
        slots: Current slot values

    Returns:
        PlaceSearchParams object for the response
    """
    query = "business"  # Default
    area = "Australia"  # Default

    if spec.place_query_slot:
        query = str(slots.get(spec.place_query_slot, query))

    if spec.place_area_slot:
        area = str(slots.get(spec.place_area_slot, area))

    return PlaceSearchParams(query=query, area=area)


# =============================================================================
# MAIN PLANNER
# =============================================================================

def decide_next_action(
    spec: AgentSpec,
    slots: Dict[str, Any],
    client_action: Optional[str] = None,
    user_message: str = "",
    current_question_slot: Optional[str] = None,
) -> PlannerResult:
    """
    Decide the next action in the conversation flow.

    This is the main entry point for the deterministic planner.
    It returns a PlannerResult with the next action and any associated data.

    Rules:
    1. If client_action == CONFIRM => COMPLETE
    2. If client_action == REJECT => ASK_QUESTION (ask for first missing or let user specify)
    3. If asking for PHONE and user wants to search => FIND_PLACE
    4. If all required slots filled => CONFIRM
    5. Otherwise => ASK_QUESTION for next missing slot

    Args:
        spec: The agent specification
        slots: Current slot values (already merged)
        client_action: Optional client action (CONFIRM or REJECT)
        user_message: The user's message (for FIND_PLACE detection)
        current_question_slot: The slot we're currently asking for (for FIND_PLACE detection)

    Returns:
        PlannerResult with the decision and associated data
    """
    # Rule 1: CONFIRM action => COMPLETE
    if client_action == ClientAction.CONFIRM.value or client_action == "CONFIRM":
        logger.info(f"Planner: client_action=CONFIRM => COMPLETE")
        return PlannerResult(
            next_action=NextAction.COMPLETE,
            assistant_message="Great! I'll place the call now.",
        )

    # Rule 2: REJECT action => ASK_QUESTION
    if client_action == ClientAction.REJECT.value or client_action == "REJECT":
        logger.info(f"Planner: client_action=REJECT => ASK_QUESTION")
        # Ask what they want to change, or restart from first missing slot
        next_slot = get_next_slot(spec, slots)
        if next_slot:
            question = build_question(next_slot)
            return PlannerResult(
                next_action=NextAction.ASK_QUESTION,
                question=question,
                assistant_message=f"No problem! {next_slot.prompt}",
            )
        else:
            # All slots filled but user rejected - let them specify
            return PlannerResult(
                next_action=NextAction.ASK_QUESTION,
                assistant_message="What would you like to change?",
            )

    # Get current slot spec if we have the name
    current_slot_spec = None
    if current_question_slot:
        current_slot_spec = spec.get_slot_by_name(current_question_slot)

    # Rule 3: Check for FIND_PLACE trigger (only for PHONE slots)
    if should_trigger_find_place(user_message, current_slot_spec):
        logger.info(f"Planner: FIND_PLACE triggered by user message")
        place_params = build_place_search_params(spec, slots)
        return PlannerResult(
            next_action=NextAction.FIND_PLACE,
            place_search_params=place_params,
            assistant_message="I'll help you find the number.",
        )

    # Rule 4 & 5: Check if all required slots are filled
    next_slot = get_next_slot(spec, slots)

    if next_slot is None:
        # All required slots filled => CONFIRM
        logger.info(f"Planner: All required slots filled => CONFIRM")
        confirmation_card = build_confirmation_card(spec, slots)
        return PlannerResult(
            next_action=NextAction.CONFIRM,
            confirmation_card=confirmation_card,
            assistant_message="Let me confirm the details:",
        )
    else:
        # Still have slots to fill => ASK_QUESTION
        logger.info(f"Planner: Next slot to ask: {next_slot.name}")
        question = build_question(next_slot)
        return PlannerResult(
            next_action=NextAction.ASK_QUESTION,
            question=question,
            assistant_message=next_slot.prompt,
        )
