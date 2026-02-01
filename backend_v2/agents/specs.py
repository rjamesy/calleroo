"""
AgentSpec and SlotSpec definitions.

This module defines the declarative specification for each agent type.
The planner and extractor use these specs to drive conversation flow
deterministically, without per-agent branching logic.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Callable


class InputType(str, Enum):
    """Input types for slots."""
    TEXT = "TEXT"
    PHONE = "PHONE"
    DATE = "DATE"
    TIME = "TIME"
    NUMBER = "NUMBER"
    CHOICE = "CHOICE"
    YES_NO = "YES_NO"


class PhoneFlowMode(str, Enum):
    """How the live phone call is conducted."""
    DETERMINISTIC_SCRIPT = "DETERMINISTIC_SCRIPT"  # Fixed TwiML, no OpenAI
    LLM_DIALOG = "LLM_DIALOG"  # OpenAI-driven conversation


class PhoneSource(str, Enum):
    """Where the phone number comes from."""
    PLACE = "PLACE"  # From place search (Google Places)
    DIRECT_SLOT = "DIRECT_SLOT"  # From a slot collected during conversation


@dataclass
class Choice:
    """A choice option for CHOICE or YES_NO input types."""
    label: str
    value: str


@dataclass
class SlotSpec:
    """
    Specification for a single slot to collect.

    Attributes:
        name: The slot key (e.g., "employer_name", "shift_date")
        required: Whether this slot must be filled before confirmation
        input_type: The type of input expected
        prompt: The question to ask the user for this slot
        choices: For CHOICE type, the available options
        validators: Optional list of validator function names
        normalizers: Optional list of normalizer function names
        description: Human-readable description for debugging
    """
    name: str
    required: bool
    input_type: InputType
    prompt: str
    choices: Optional[List[Choice]] = None
    validators: Optional[List[str]] = None
    normalizers: Optional[List[str]] = None
    description: Optional[str] = None

    def get_quick_replies(self) -> Optional[List[Dict[str, str]]]:
        """
        Get quick replies for this slot based on input type.
        Returns list of {label, value} dicts for UI chips.
        """
        if self.input_type == InputType.CHOICE and self.choices:
            return [{"label": c.label, "value": c.value} for c in self.choices]
        elif self.input_type == InputType.YES_NO:
            return [
                {"label": "Yes", "value": "YES"},
                {"label": "No", "value": "NO"},
            ]
        return None


@dataclass
class PhoneFlow:
    """Configuration for the live phone call."""
    mode: PhoneFlowMode
    greeting_template: Optional[str] = None  # For DETERMINISTIC_SCRIPT
    message_template: Optional[str] = None  # For DETERMINISTIC_SCRIPT
    system_prompt_template: Optional[str] = None  # For LLM_DIALOG


@dataclass
class AgentSpec:
    """
    Complete specification for an agent type.

    This drives all conversation flow, call brief generation, and phone calls
    without any per-agent if/else branching.
    """
    agent_type: str
    title: str
    description: str

    # Slots in collection order (required slots first, then optional)
    slots_in_order: List[SlotSpec]

    # Confirmation card template
    confirm_title: str
    confirm_lines: List[str]  # Template strings with {slot_name} placeholders

    # Phone number source
    phone_source: PhoneSource
    direct_phone_slot: Optional[str] = None  # Required if phone_source == DIRECT_SLOT

    # Phone call configuration
    phone_flow: PhoneFlow = field(default_factory=lambda: PhoneFlow(mode=PhoneFlowMode.LLM_DIALOG))

    # Call brief templates
    objective_template: Optional[str] = None
    script_template: Optional[str] = None

    # Place search configuration (for PLACE phone source)
    place_query_slot: Optional[str] = None  # Slot to use for place search query
    place_area_slot: Optional[str] = None  # Slot to use for place search area

    def get_required_slots(self) -> List[SlotSpec]:
        """Get all required slots in order."""
        return [s for s in self.slots_in_order if s.required]

    def get_optional_slots(self) -> List[SlotSpec]:
        """Get all optional slots in order."""
        return [s for s in self.slots_in_order if not s.required]

    def get_slot_by_name(self, name: str) -> Optional[SlotSpec]:
        """Get a slot spec by name."""
        for slot in self.slots_in_order:
            if slot.name == name:
                return slot
        return None

    def get_slot_names(self) -> List[str]:
        """Get all slot names in order."""
        return [s.name for s in self.slots_in_order]

    def get_required_slot_names(self) -> List[str]:
        """Get required slot names in order."""
        return [s.name for s in self.slots_in_order if s.required]


# =============================================================================
# AGENT REGISTRY
# =============================================================================

SICK_CALLER_SPEC = AgentSpec(
    agent_type="SICK_CALLER",
    title="Call in Sick",
    description="Notify your workplace that you are unwell",

    slots_in_order=[
        SlotSpec(
            name="employer_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="Who should I call to notify? (e.g., your manager's name or company name)",
            description="Name of employer/manager to call"
        ),
        SlotSpec(
            name="employer_phone",
            required=True,
            input_type=InputType.PHONE,
            prompt="What's their phone number?",
            description="Phone number to call"
        ),
        SlotSpec(
            name="caller_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="What name should I give them? (your name)",
            description="User's name to provide"
        ),
        SlotSpec(
            name="shift_date",
            required=True,
            input_type=InputType.DATE,
            prompt="When is your shift?",
            description="Date of the shift being missed"
        ),
        SlotSpec(
            name="shift_start_time",
            required=True,
            input_type=InputType.TIME,
            prompt="What time does your shift start?",
            description="Start time of the shift"
        ),
        SlotSpec(
            name="reason_category",
            required=True,
            input_type=InputType.CHOICE,
            prompt="What's the reason for calling in?",
            choices=[
                Choice(label="I'm sick", value="SICK"),
                Choice(label="Caring for someone", value="CARER"),
                Choice(label="Mental health day", value="MENTAL_HEALTH"),
                Choice(label="Medical appointment", value="MEDICAL_APPOINTMENT"),
            ],
            description="Reason category for absence"
        ),
        SlotSpec(
            name="expected_return_date",
            required=False,
            input_type=InputType.DATE,
            prompt="When do you expect to return? (optional)",
            description="Expected return date"
        ),
        SlotSpec(
            name="note_for_team",
            required=False,
            input_type=InputType.TEXT,
            prompt="Any message for your team? (optional)",
            description="Additional note"
        ),
    ],

    confirm_title="Call In Sick",
    confirm_lines=[
        "Calling: {employer_name}",
        "Phone: {employer_phone}",
        "Your name: {caller_name}",
        "Shift: {shift_date} at {shift_start_time}",
        "Reason: {reason_category}",
    ],

    phone_source=PhoneSource.DIRECT_SLOT,
    direct_phone_slot="employer_phone",

    phone_flow=PhoneFlow(
        mode=PhoneFlowMode.DETERMINISTIC_SCRIPT,
        greeting_template="Hi, this is an automated call on behalf of {caller_name}.",
        message_template=(
            "{caller_name} won't be able to make their shift on {shift_date} at {shift_start_time}. "
            "The reason is {reason_category}. Could you please confirm you've received this message?"
        ),
    ),

    objective_template="Notify {employer_name} that {caller_name} cannot attend their shift on {shift_date}",
    script_template=(
        "Call {employer_name} at {employer_phone} to notify them that {caller_name} "
        "cannot attend their shift on {shift_date} at {shift_start_time} due to {reason_category}."
    ),
)


STOCK_CHECKER_SPEC = AgentSpec(
    agent_type="STOCK_CHECKER",
    title="Stock Check",
    description="Check product availability at retailers",

    slots_in_order=[
        SlotSpec(
            name="retailer_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="Which retailer should I call?",
            description="Name of the retailer"
        ),
        SlotSpec(
            name="product_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="What product are you looking for?",
            description="Product to check availability"
        ),
        SlotSpec(
            name="quantity",
            required=True,
            input_type=InputType.NUMBER,
            prompt="How many do you need?",
            description="Quantity needed"
        ),
        SlotSpec(
            name="store_location",
            required=True,
            input_type=InputType.TEXT,
            prompt="Which suburb or area should I search in?",
            description="Location for store search"
        ),
        SlotSpec(
            name="brand",
            required=False,
            input_type=InputType.TEXT,
            prompt="Any specific brand? (optional)",
            description="Brand preference"
        ),
        SlotSpec(
            name="model",
            required=False,
            input_type=InputType.TEXT,
            prompt="Any specific model? (optional)",
            description="Model number or name"
        ),
        SlotSpec(
            name="variant",
            required=False,
            input_type=InputType.TEXT,
            prompt="Any specific variant (size, color)? (optional)",
            description="Variant details"
        ),
    ],

    confirm_title="Check Stock",
    confirm_lines=[
        "Retailer: {retailer_name}",
        "Product: {product_name}",
        "Quantity: {quantity}",
        "Location: {store_location}",
    ],

    phone_source=PhoneSource.PLACE,
    place_query_slot="retailer_name",
    place_area_slot="store_location",

    phone_flow=PhoneFlow(
        mode=PhoneFlowMode.LLM_DIALOG,
        system_prompt_template=(
            "You are calling {retailer_name} to check if they have {product_name} in stock. "
            "The customer needs {quantity} units. Be polite, identify yourself as an AI assistant, "
            "and ask about availability. If out of stock, ask about ETA or nearby stores."
        ),
    ),

    objective_template="Check if {retailer_name} has {quantity}x {product_name} in stock",
    script_template=(
        "Call {retailer_name} to check availability of {product_name}. "
        "Customer needs {quantity} units near {store_location}."
    ),
)


RESTAURANT_RESERVATION_SPEC = AgentSpec(
    agent_type="RESTAURANT_RESERVATION",
    title="Book Restaurant",
    description="Book a table at a restaurant",

    slots_in_order=[
        SlotSpec(
            name="restaurant_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="Which restaurant would you like to book?",
            description="Name of the restaurant"
        ),
        SlotSpec(
            name="party_size",
            required=True,
            input_type=InputType.NUMBER,
            prompt="How many people?",
            description="Number of guests"
        ),
        SlotSpec(
            name="date",
            required=True,
            input_type=InputType.DATE,
            prompt="What date would you like to book for?",
            description="Reservation date"
        ),
        SlotSpec(
            name="time",
            required=True,
            input_type=InputType.TIME,
            prompt="What time would you prefer?",
            description="Reservation time"
        ),
        SlotSpec(
            name="suburb_or_area",
            required=False,
            input_type=InputType.TEXT,
            prompt="Which suburb or area? (optional if restaurant name is unique)",
            description="Location area"
        ),
        SlotSpec(
            name="share_contact",
            required=False,
            input_type=InputType.YES_NO,
            prompt="Should I share your contact details with the restaurant?",
            description="Whether to share contact info"
        ),
    ],

    confirm_title="Book Restaurant",
    confirm_lines=[
        "Restaurant: {restaurant_name}",
        "Party size: {party_size} people",
        "Date: {date}",
        "Time: {time}",
    ],

    phone_source=PhoneSource.PLACE,
    place_query_slot="restaurant_name",
    place_area_slot="suburb_or_area",

    phone_flow=PhoneFlow(
        mode=PhoneFlowMode.LLM_DIALOG,
        system_prompt_template=(
            "You are calling {restaurant_name} to make a reservation. "
            "Request a table for {party_size} people on {date} at {time}. "
            "Be polite, identify yourself as an AI assistant making a booking on behalf of a customer."
        ),
    ),

    objective_template="Book a table for {party_size} at {restaurant_name} on {date} at {time}",
    script_template=(
        "Call {restaurant_name} to book a table for {party_size} people on {date} at {time}."
    ),
)


CANCEL_APPOINTMENT_SPEC = AgentSpec(
    agent_type="CANCEL_APPOINTMENT",
    title="Cancel Appointment",
    description="Cancel an existing booking",

    slots_in_order=[
        SlotSpec(
            name="business_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="What's the name of the business where you have the appointment?",
            description="Business name"
        ),
        SlotSpec(
            name="appointment_day",
            required=True,
            input_type=InputType.DATE,
            prompt="What day is your appointment?",
            description="Appointment date"
        ),
        SlotSpec(
            name="appointment_time",
            required=True,
            input_type=InputType.TIME,
            prompt="What time is the appointment?",
            description="Appointment time"
        ),
        SlotSpec(
            name="customer_name",
            required=True,
            input_type=InputType.TEXT,
            prompt="What name is the booking under?",
            description="Name on the booking"
        ),
        SlotSpec(
            name="business_location",
            required=False,
            input_type=InputType.TEXT,
            prompt="Which location/branch? (optional if only one location)",
            description="Business location"
        ),
        SlotSpec(
            name="cancel_reason",
            required=False,
            input_type=InputType.TEXT,
            prompt="Any reason to provide? (optional)",
            description="Cancellation reason"
        ),
        SlotSpec(
            name="reschedule_intent",
            required=False,
            input_type=InputType.YES_NO,
            prompt="Would you like to reschedule?",
            description="Whether to ask about rescheduling"
        ),
    ],

    confirm_title="Cancel Appointment",
    confirm_lines=[
        "Business: {business_name}",
        "Appointment: {appointment_day} at {appointment_time}",
        "Name on booking: {customer_name}",
    ],

    phone_source=PhoneSource.PLACE,
    place_query_slot="business_name",
    place_area_slot="business_location",

    phone_flow=PhoneFlow(
        mode=PhoneFlowMode.LLM_DIALOG,
        system_prompt_template=(
            "You are calling {business_name} to cancel an appointment. "
            "The appointment is on {appointment_day} at {appointment_time} under the name {customer_name}. "
            "Be polite, identify yourself as an AI assistant, and confirm the cancellation."
        ),
    ),

    objective_template="Cancel appointment at {business_name} on {appointment_day} at {appointment_time}",
    script_template=(
        "Call {business_name} to cancel the appointment on {appointment_day} at {appointment_time} "
        "under the name {customer_name}."
    ),
)


# =============================================================================
# REGISTRY
# =============================================================================

AGENTS: Dict[str, AgentSpec] = {
    "SICK_CALLER": SICK_CALLER_SPEC,
    "STOCK_CHECKER": STOCK_CHECKER_SPEC,
    "RESTAURANT_RESERVATION": RESTAURANT_RESERVATION_SPEC,
    "CANCEL_APPOINTMENT": CANCEL_APPOINTMENT_SPEC,
}


def get_agent_spec(agent_type: str) -> AgentSpec:
    """
    Get the AgentSpec for a given agent type.

    Raises:
        ValueError: If agent type is not found in registry.
    """
    spec = AGENTS.get(agent_type)
    if spec is None:
        raise ValueError(f"Unknown agent type: {agent_type}. Valid types: {list(AGENTS.keys())}")
    return spec
