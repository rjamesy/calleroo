"""
Slot extraction logic.

This module handles extracting slot values from user messages.
It uses a tiered approach:
1. Tier A (Deterministic): Pattern matching for structured inputs
2. Tier B (LLM Parser): OpenAI for free-form text extraction

The LLM is ONLY used as a parser, never for planning or question selection.
"""
import re
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, Any, Optional, List, Tuple
import asyncio

from agents.specs import AgentSpec, SlotSpec, InputType, Choice

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of slot extraction."""
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    llm_used: bool = False
    llm_model: Optional[str] = None
    confidence: str = "HIGH"  # HIGH for deterministic, MEDIUM/LOW for LLM


# =============================================================================
# TIER A: DETERMINISTIC EXTRACTION
# =============================================================================

def extract_choice_value(
    user_message: str,
    slot_spec: SlotSpec,
) -> Optional[str]:
    """
    Extract a CHOICE value from user message.

    Accepts:
    - Exact value match (e.g., "SICK")
    - Label match (e.g., "I'm sick")
    - Partial label match (e.g., "sick")

    Returns:
        The choice value if matched, None otherwise
    """
    if not slot_spec.choices:
        return None

    message_lower = user_message.lower().strip()

    for choice in slot_spec.choices:
        # Exact value match
        if message_lower == choice.value.lower():
            return choice.value

        # Exact label match
        if message_lower == choice.label.lower():
            return choice.value

        # Partial label match (label contains in message or message contains label)
        label_lower = choice.label.lower()
        # Remove common prefixes like "I'm", "I am"
        clean_label = label_lower.replace("i'm ", "").replace("i am ", "")
        if clean_label in message_lower or message_lower in label_lower:
            return choice.value

    return None


def extract_yes_no_value(user_message: str) -> Optional[str]:
    """
    Extract a YES/NO value from user message.

    Returns:
        "YES", "NO", or None if not determinable
    """
    message_lower = user_message.lower().strip()

    yes_patterns = ["yes", "yeah", "yep", "sure", "ok", "okay", "yup", "absolutely", "definitely", "please", "y"]
    no_patterns = ["no", "nope", "nah", "not", "don't", "dont", "n"]

    for pattern in yes_patterns:
        if message_lower == pattern or message_lower.startswith(pattern + " "):
            return "YES"

    for pattern in no_patterns:
        if message_lower == pattern or message_lower.startswith(pattern + " "):
            return "NO"

    return None


def normalize_phone_number(phone: str) -> Optional[str]:
    """
    Attempt to normalize a phone number to E.164 format.

    This is a best-effort normalization for Australian numbers.
    Returns None if the number doesn't look like a valid phone.

    Args:
        phone: Raw phone input

    Returns:
        E.164 formatted number or None
    """
    # Remove all non-digit characters except leading +
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r'\D', '', phone)

    if not digits:
        return None

    # Australian number normalization
    if len(digits) == 10 and digits.startswith("0"):
        # 0412345678 -> +61412345678
        return f"+61{digits[1:]}"
    elif len(digits) == 9 and digits.startswith("4"):
        # 412345678 -> +61412345678
        return f"+61{digits}"
    elif len(digits) == 11 and digits.startswith("61"):
        # 61412345678 -> +61412345678
        return f"+{digits}"
    elif len(digits) >= 10 and has_plus:
        # Already has country code with +
        return f"+{digits}"
    elif len(digits) >= 10:
        # Assume it might be valid, return with + if looks international
        if digits.startswith("1") or digits.startswith("44") or digits.startswith("61"):
            return f"+{digits}"
        # Australian landline with area code
        if len(digits) == 10 and digits.startswith("0"):
            return f"+61{digits[1:]}"

    # Can't normalize, but might still be usable
    if len(digits) >= 8:
        return phone.strip()

    return None


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse a date string into ISO format (YYYY-MM-DD).

    Handles common formats and relative dates like "today", "tomorrow".

    Args:
        date_str: Raw date input

    Returns:
        ISO date string or None if unparseable
    """
    date_lower = date_str.lower().strip()
    today = date.today()

    # Relative dates
    if date_lower in ["today", "now"]:
        return today.isoformat()
    elif date_lower in ["tomorrow", "tmrw", "tmr"]:
        from datetime import timedelta
        return (today + timedelta(days=1)).isoformat()

    # Try common date formats
    formats = [
        "%Y-%m-%d",  # 2026-02-01
        "%d/%m/%Y",  # 01/02/2026
        "%d-%m-%Y",  # 01-02-2026
        "%d/%m/%y",  # 01/02/26
        "%d-%m-%y",  # 01-02-26
        "%B %d, %Y",  # February 1, 2026
        "%B %d %Y",  # February 1 2026
        "%b %d, %Y",  # Feb 1, 2026
        "%b %d %Y",  # Feb 1 2026
        "%d %B %Y",  # 1 February 2026
        "%d %b %Y",  # 1 Feb 2026
        "%d %B",  # 1 February (assume current year)
        "%d %b",  # 1 Feb
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            # If year not in format, use current year
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def parse_time(time_str: str) -> Optional[str]:
    """
    Parse a time string into HH:MM format.

    Handles common formats like "2pm", "14:00", "2:30 PM".

    Args:
        time_str: Raw time input

    Returns:
        24-hour time string (HH:MM) or None if unparseable
    """
    time_lower = time_str.lower().strip()

    # Simple patterns
    formats = [
        "%H:%M",  # 14:00
        "%H:%M:%S",  # 14:00:00
        "%I:%M %p",  # 2:00 PM
        "%I:%M%p",  # 2:00PM
        "%I %p",  # 2 PM
        "%I%p",  # 2PM
    ]

    # Normalize common variations
    normalized = time_lower.replace(".", ":").replace("am", " am").replace("pm", " pm")
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue

    # Try simple hour match like "2pm" or "14"
    match = re.match(r'^(\d{1,2})\s*(am|pm)?$', time_lower)
    if match:
        hour = int(match.group(1))
        period = match.group(2)

        if period == "pm" and hour < 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        if 0 <= hour <= 23:
            return f"{hour:02d}:00"

    return None


def parse_number(num_str: str) -> Optional[int]:
    """
    Parse a number from a string.

    Handles written numbers like "one", "two" as well as digits.

    Args:
        num_str: Raw number input

    Returns:
        Integer or None if unparseable
    """
    num_lower = num_str.lower().strip()

    # Written numbers
    word_to_num = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12,
    }

    if num_lower in word_to_num:
        return word_to_num[num_lower]

    # Extract first number from string
    match = re.search(r'\d+', num_str)
    if match:
        return int(match.group())

    return None


def extract_slot_deterministic(
    user_message: str,
    slot_spec: SlotSpec,
) -> Tuple[Optional[Any], bool]:
    """
    Try to extract a slot value deterministically.

    Args:
        user_message: The user's message
        slot_spec: The slot specification

    Returns:
        Tuple of (extracted_value, success)
    """
    input_type = slot_spec.input_type

    if input_type == InputType.CHOICE:
        value = extract_choice_value(user_message, slot_spec)
        return (value, value is not None)

    elif input_type == InputType.YES_NO:
        value = extract_yes_no_value(user_message)
        return (value, value is not None)

    elif input_type == InputType.PHONE:
        value = normalize_phone_number(user_message)
        return (value, value is not None)

    elif input_type == InputType.DATE:
        value = parse_date(user_message)
        return (value, value is not None)

    elif input_type == InputType.TIME:
        value = parse_time(user_message)
        return (value, value is not None)

    elif input_type == InputType.NUMBER:
        value = parse_number(user_message)
        return (value, value is not None)

    elif input_type == InputType.TEXT:
        # For TEXT, accept anything non-empty as valid
        value = user_message.strip()
        return (value if value else None, bool(value))

    return (None, False)


# =============================================================================
# TIER B: LLM EXTRACTION
# =============================================================================

def build_extraction_prompt(
    spec: AgentSpec,
    user_message: str,
    current_slot: Optional[str],
    existing_slots: Dict[str, Any],
) -> str:
    """
    Build the prompt for LLM extraction.

    The LLM is instructed to ONLY extract data, never plan or ask questions.

    Args:
        spec: Agent specification
        user_message: The user's message
        current_slot: The slot we're currently asking for
        existing_slots: Already collected slots

    Returns:
        Prompt string for OpenAI
    """
    slot_definitions = []
    for slot in spec.slots_in_order:
        slot_def = f"- {slot.name} ({slot.input_type.value})"
        if slot.choices:
            choices_str = ", ".join([f'"{c.value}"' for c in slot.choices])
            slot_def += f" [allowed values: {choices_str}]"
        slot_definitions.append(slot_def)

    prompt = f"""Extract slot values from the user message.

SLOTS TO EXTRACT:
{chr(10).join(slot_definitions)}

CURRENT SLOT BEING ASKED: {current_slot or "none"}

EXISTING SLOTS: {json.dumps(existing_slots)}

USER MESSAGE: "{user_message}"

INSTRUCTIONS:
1. Extract ONLY the slots that have values in the user message
2. Use the EXACT slot names listed above
3. For CHOICE slots, use ONLY the allowed values
4. For DATE, use ISO format (YYYY-MM-DD)
5. For TIME, use 24-hour format (HH:MM)
6. For PHONE, normalize to E.164 format if possible (+61...)
7. Do NOT include slots that aren't mentioned
8. Do NOT make up values
9. Do NOT ask questions or provide any other text

OUTPUT FORMAT (JSON only, no other text):
{{"extractedData": {{"slot_name": "value", ...}}}}

If no slots can be extracted, return:
{{"extractedData": {{}}}}"""

    return prompt


async def extract_with_llm(
    spec: AgentSpec,
    user_message: str,
    current_slot: Optional[str],
    existing_slots: Dict[str, Any],
    openai_client: Any,
    model: str = "gpt-4o-mini",
) -> ExtractionResult:
    """
    Extract slots using OpenAI as a parser.

    Args:
        spec: Agent specification
        user_message: The user's message
        current_slot: The slot we're currently asking for
        existing_slots: Already collected slots
        openai_client: OpenAI async client
        model: Model to use

    Returns:
        ExtractionResult with extracted data
    """
    prompt = build_extraction_prompt(spec, user_message, current_slot, existing_slots)

    try:
        response = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a slot extraction assistant. Output ONLY valid JSON, nothing else."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        logger.debug(f"LLM extraction response: {content}")

        data = json.loads(content)
        extracted = data.get("extractedData", {})

        # Sanitize: only keep known slot names
        known_slots = set(s.name for s in spec.slots_in_order)
        sanitized = {k: v for k, v in extracted.items() if k in known_slots and v is not None and v != ""}

        return ExtractionResult(
            extracted_data=sanitized,
            llm_used=True,
            llm_model=model,
            confidence="MEDIUM",
        )

    except json.JSONDecodeError as e:
        logger.warning(f"LLM extraction JSON parse error: {e}")
        return ExtractionResult(
            extracted_data={},
            llm_used=True,
            llm_model=model,
            confidence="LOW",
        )
    except Exception as e:
        logger.error(f"LLM extraction error: {e}")
        return ExtractionResult(
            extracted_data={},
            llm_used=True,
            llm_model=model,
            confidence="LOW",
        )


# =============================================================================
# MAIN EXTRACTION FUNCTION
# =============================================================================

async def extract_slots(
    spec: AgentSpec,
    user_message: str,
    current_slot: Optional[str] = None,
    existing_slots: Optional[Dict[str, Any]] = None,
    openai_client: Any = None,
    model: str = "gpt-4o-mini",
) -> ExtractionResult:
    """
    Extract slot values from user message.

    Uses tiered extraction:
    1. If we know the current slot, try deterministic extraction first
    2. Fall back to LLM for free-form text or failed deterministic

    Args:
        spec: Agent specification
        user_message: The user's message
        current_slot: The slot we're currently asking for (if known)
        existing_slots: Already collected slots
        openai_client: OpenAI async client (required for Tier B)
        model: Model to use for LLM extraction

    Returns:
        ExtractionResult with extracted data
    """
    if existing_slots is None:
        existing_slots = {}

    if not user_message or not user_message.strip():
        return ExtractionResult(extracted_data={}, confidence="HIGH")

    result = ExtractionResult(extracted_data={}, confidence="HIGH")

    # Tier A: Try deterministic extraction for current slot
    if current_slot:
        slot_spec = spec.get_slot_by_name(current_slot)
        if slot_spec:
            value, success = extract_slot_deterministic(user_message, slot_spec)
            if success and value is not None:
                result.extracted_data[current_slot] = value
                logger.info(f"Deterministic extraction: {current_slot}={value}")
                return result

    # Tier B: Use LLM for complex extraction
    if openai_client:
        llm_result = await extract_with_llm(
            spec=spec,
            user_message=user_message,
            current_slot=current_slot,
            existing_slots=existing_slots,
            openai_client=openai_client,
            model=model,
        )

        # Merge deterministic results with LLM results (deterministic takes precedence)
        merged = {**llm_result.extracted_data, **result.extracted_data}
        result.extracted_data = merged
        result.llm_used = llm_result.llm_used
        result.llm_model = llm_result.llm_model
        result.confidence = llm_result.confidence if not result.extracted_data else result.confidence

    return result


def extract_slots_sync(
    spec: AgentSpec,
    user_message: str,
    current_slot: Optional[str] = None,
    existing_slots: Optional[Dict[str, Any]] = None,
) -> ExtractionResult:
    """
    Synchronous version of extract_slots (deterministic only, no LLM).

    Use this when you don't need LLM extraction.

    Args:
        spec: Agent specification
        user_message: The user's message
        current_slot: The slot we're currently asking for
        existing_slots: Already collected slots

    Returns:
        ExtractionResult with extracted data (deterministic only)
    """
    if existing_slots is None:
        existing_slots = {}

    if not user_message or not user_message.strip():
        return ExtractionResult(extracted_data={}, confidence="HIGH")

    result = ExtractionResult(extracted_data={}, confidence="HIGH")

    # Try deterministic extraction for current slot
    if current_slot:
        slot_spec = spec.get_slot_by_name(current_slot)
        if slot_spec:
            value, success = extract_slot_deterministic(user_message, slot_spec)
            if success and value is not None:
                result.extracted_data[current_slot] = value
                logger.info(f"Deterministic extraction: {current_slot}={value}")

    return result
