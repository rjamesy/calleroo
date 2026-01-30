"""
Call Brief Service - generates call script preview via OpenAI.

This service:
1. Deterministically checks for missing required fields (NOT OpenAI)
2. Calls OpenAI to generate objective, scriptPreview, and checklist
3. Never caches - always calls OpenAI

Python 3.9 compatible - uses typing.Dict, typing.List, typing.Optional, typing.Tuple
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from .models import (
    CallBriefDisclosure,
    CallBriefFallbacks,
    CallBriefPlace,
    CallBriefResponseV2,
)

logger = logging.getLogger(__name__)

# Chain retailers that require store_location
CHAIN_RETAILERS = [
    "bunnings", "jb hi-fi", "jb hifi", "officeworks", "harvey norman",
    "the good guys", "bcf", "anaconda", "rebel", "kmart", "target",
    "big w", "woolworths", "coles", "ikea", "aldi", "costco",
    "supercheap auto", "repco", "autobarn", "total tools", "sydney tools",
    "masters", "mitre 10", "home hardware"
]


def is_chain_retailer(retailer_name: str) -> bool:
    """Check if a retailer is a chain (requires store_location)."""
    if not retailer_name:
        return False
    normalized = retailer_name.lower().strip()
    return any(chain in normalized for chain in CHAIN_RETAILERS)


def compute_missing_required_fields(
    agent_type: str,
    slots: Dict[str, Any]
) -> List[str]:
    """
    Deterministically compute which required fields are missing.
    This does NOT call OpenAI - it's pure logic.
    """
    missing: List[str] = []

    if agent_type == "STOCK_CHECKER":
        # Required: retailer_name, product_name, quantity (defaults to 1)
        if not slots.get("retailer_name"):
            missing.append("retailer_name")
        if not slots.get("product_name"):
            missing.append("product_name")
        # quantity defaults to 1, so only missing if explicitly null
        if slots.get("quantity") is None and "quantity" not in slots:
            # If quantity not in slots at all, it's OK - will default to 1
            pass

        # Conditionally required: store_location for chain retailers
        retailer = slots.get("retailer_name", "")
        if is_chain_retailer(retailer) and not slots.get("store_location"):
            missing.append("store_location")

    elif agent_type == "RESTAURANT_RESERVATION":
        # Required: restaurant_name, party_size, date, time
        if not slots.get("restaurant_name"):
            missing.append("restaurant_name")
        if not slots.get("party_size"):
            missing.append("party_size")
        if not slots.get("date"):
            missing.append("date")
        if not slots.get("time"):
            missing.append("time")

    return missing


def validate_phone_e164(phone: str) -> bool:
    """
    Validate E.164 phone format: starts with +, followed by digits only.
    Examples: +61731824583, +14155551234
    """
    if not phone:
        return False
    pattern = r'^\+[1-9]\d{6,14}$'
    return bool(re.match(pattern, phone))


CALL_BRIEF_SYSTEM_PROMPT = """You are generating a call script preview for Calleroo, an AI assistant that makes phone calls on behalf of users.

Your task is to generate THREE things based on the provided context:
1. objective: A single sentence describing the call's purpose (max 100 chars)
2. scriptPreview: A plain-text call script preview (~5-8 lines) showing what the AI will say
3. confirmationChecklist: 3-5 items the user should verify before the call starts

CONTEXT FORMAT:
- agentType: "STOCK_CHECKER" or "RESTAURANT_RESERVATION"
- place: Business being called (name, address, phone)
- slots: Collected information (product, quantity, date, time, etc.)
- disclosure: User preferences (nameShare, phoneShare)
- fallbacks: Fallback behaviors if primary goal fails

SCRIPT PREVIEW RULES:
1. Write as plain text, NO markdown
2. Include "Hello, my name is Calleroo, an AI assistant..."
3. If disclosure.nameShare is true, mention calling on behalf of [user's name]
4. If disclosure.phoneShare is true, mention user can be reached at [their number]
5. Keep it natural and conversational
6. For STOCK_CHECKER: Ask about product availability, quantity, and any relevant details
7. For RESTAURANT_RESERVATION: Request a reservation for party_size on date at time

CHECKLIST RULES:
1. Include 3-5 actionable items
2. First item should confirm the business being called
3. Include key details specific to the request (product/quantity or date/time/party size)
4. If disclosures are enabled, remind user their info will be shared

RESPONSE FORMAT (JSON only, no markdown):
{
  "objective": "Single sentence describing call purpose",
  "scriptPreview": "Multi-line plain text script preview",
  "confirmationChecklist": ["Item 1", "Item 2", "Item 3"]
}"""


class CallBriefService:
    """Service for generating call briefs via OpenAI."""

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required")

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        logger.info(f"CallBriefService configured with model: {self.model}")

    async def generate_brief(
        self,
        agent_type: str,
        place: CallBriefPlace,
        slots: Dict[str, Any],
        disclosure: CallBriefDisclosure,
        fallbacks: CallBriefFallbacks,
    ) -> Tuple[str, str, List[str]]:
        """
        Call OpenAI to generate call brief.

        Args:
            agent_type: "STOCK_CHECKER" or "RESTAURANT_RESERVATION"
            place: Place information (name, address, phone)
            slots: Collected conversation slots
            disclosure: User disclosure settings
            fallbacks: Fallback behaviors

        Returns:
            Tuple of (objective, scriptPreview, confirmationChecklist)

        Raises:
            ValueError: If OpenAI returns invalid response
        """
        # Build context message
        context = self._build_context(agent_type, place, slots, disclosure, fallbacks)

        messages = [
            {"role": "system", "content": CALL_BRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        logger.info(f"Calling OpenAI ({self.model}) for call brief generation")

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        logger.debug(f"OpenAI call brief response: {content[:500] if content else 'empty'}...")

        return self._parse_response(content)

    def _build_context(
        self,
        agent_type: str,
        place: CallBriefPlace,
        slots: Dict[str, Any],
        disclosure: CallBriefDisclosure,
        fallbacks: CallBriefFallbacks,
    ) -> str:
        """Build context message for OpenAI."""
        parts = [
            f"Agent Type: {agent_type}",
            "",
            "Place:",
            f"  Business Name: {place.businessName}",
            f"  Address: {place.formattedAddress or 'Not provided'}",
            f"  Phone: {place.phoneE164}",
            "",
            f"Slots: {json.dumps(slots)}",
            "",
            "Disclosure:",
            f"  Share my name: {disclosure.nameShare}",
            f"  Share my phone: {disclosure.phoneShare}",
            "",
            "Fallbacks:",
        ]

        # Add relevant fallbacks based on agent type
        if agent_type == "STOCK_CHECKER":
            if fallbacks.askETA is not None:
                parts.append(f"  Ask for ETA if out of stock: {fallbacks.askETA}")
            if fallbacks.askNearestStore is not None:
                parts.append(f"  Ask about nearest store: {fallbacks.askNearestStore}")
        elif agent_type == "RESTAURANT_RESERVATION":
            if fallbacks.retryIfNoAnswer is not None:
                parts.append(f"  Retry if no answer: {fallbacks.retryIfNoAnswer}")
            if fallbacks.retryIfBusy is not None:
                parts.append(f"  Retry if busy: {fallbacks.retryIfBusy}")
            if fallbacks.leaveVoicemail is not None:
                parts.append(f"  Leave voicemail: {fallbacks.leaveVoicemail}")

        return "\n".join(parts)

    def _parse_response(self, content: Optional[str]) -> Tuple[str, str, List[str]]:
        """Parse OpenAI JSON response into components."""
        if not content:
            raise ValueError("OpenAI returned empty response")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"invalid_openai_json: Failed to parse call brief response: {content[:500]}")
            raise ValueError(f"invalid_openai_json: OpenAI returned invalid JSON: {str(e)}")

        objective = data.get("objective", "")
        script_preview = data.get("scriptPreview", "")
        checklist = data.get("confirmationChecklist", [])

        if not objective:
            raise ValueError("invalid_openai_json: Missing 'objective' field")
        if not script_preview:
            raise ValueError("invalid_openai_json: Missing 'scriptPreview' field")
        if not checklist or not isinstance(checklist, list):
            raise ValueError("invalid_openai_json: Missing or invalid 'confirmationChecklist' field")

        return objective, script_preview, checklist


# Singleton instance (created on first import when needed)
_call_brief_service: Optional[CallBriefService] = None


def get_call_brief_service() -> CallBriefService:
    """Get or create the CallBriefService singleton."""
    global _call_brief_service
    if _call_brief_service is None:
        _call_brief_service = CallBriefService()
    return _call_brief_service
