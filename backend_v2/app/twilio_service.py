"""
Twilio Service - handles real outbound calls for Step 4 MVP.

This service:
1. Places outbound calls via Twilio REST API
2. Stores call state in-memory (acceptable for MVP)
3. Handles Twilio webhooks for status updates
4. Transcribes recordings via OpenAI Whisper
5. Analyzes call outcomes via OpenAI

Python 3.9 compatible - uses typing.Dict, typing.List, typing.Optional
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI
from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)


@dataclass
class CallRun:
    """In-memory state for a single call run."""
    call_id: str  # Twilio Call SID
    conversation_id: str
    agent_type: str
    phone_e164: str
    script_preview: str
    slots: Dict[str, Any] = field(default_factory=dict)

    # Status tracking
    status: str = "queued"  # queued, ringing, in-progress, completed, failed, busy, no-answer
    started_at: datetime = field(default_factory=datetime.utcnow)
    duration_seconds: Optional[int] = None

    # Post-call processing
    recording_url: Optional[str] = None
    transcript: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # Live conversation state (for autonomous agent)
    turn: int = 1
    retry: int = 0
    live_transcript: List[str] = field(default_factory=list)

    # Async generation state for filler/poll pattern
    pending_user_speech: Optional[str] = None
    pending_agent_reply: Optional[str] = None
    is_generating: bool = False
    pending_started_at: Optional[datetime] = None

    # Repeat question detection
    last_question: Optional[str] = None

    # Terminal state - call is ending, no more Gather needed
    is_terminal: bool = False

    # Sick-caller hard state (deterministic)
    message_confirm_asked: bool = False
    message_confirm_result: Optional[str] = None  # "YES" | "NO" | "PASS_ON"

    # Call cost tracking (optional - may not be immediately available)
    cost: Optional[float] = None
    cost_currency: Optional[str] = None


# In-memory storage for call runs (acceptable for MVP)
CALL_RUNS: Dict[str, CallRun] = {}


OUTCOME_ANALYSIS_PROMPT = """Analyze this phone call and extract the outcome.

CONTEXT:
- Agent Type: {agent_type}
- Call Purpose: {script_preview}
- Slots: {slots}

EVENT TRANSCRIPT (primary - trust this for who said what):
{event_transcript}

The EVENT TRANSCRIPT above is the authoritative record of the conversation. Each line is labeled with the speaker:
- "Assistant:" = Our AI agent (Calleroo)
- "User:" = The business/person we called

{raw_transcript_section}

IMPORTANT: Trust the EVENT TRANSCRIPT for determining who said what. The raw transcript (if provided) is just supplementary audio transcription and may not correctly attribute speakers.

Based on the EVENT TRANSCRIPT, determine:
1. success: Was the call objective achieved? (true/false)
2. summary: One sentence summary of the call outcome
3. extractedFacts: Key facts extracted from the call (varies by agent type)
4. confidence: How confident are you in this analysis? (LOW, MEDIUM, HIGH)

For STOCK_CHECKER, extractedFacts should include:
- inStock: boolean
- quantity: number (if mentioned)
- price: string (if mentioned)
- eta: string (if out of stock and ETA provided)

For RESTAURANT_RESERVATION, extractedFacts should include:
- confirmed: boolean
- time: string (confirmed time)
- partySize: number
- notes: string (any special notes)

Respond with JSON only:
{{
  "success": true/false,
  "summary": "...",
  "extractedFacts": {{}},
  "confidence": "LOW|MEDIUM|HIGH"
}}"""


SICK_CALLER_PHONE_AGENT_PROMPT = """
You are Calleroo, an AI assistant placing a short phone call to notify an employer that the customer is unwell.

ABSOLUTE RULES (MUST FOLLOW):
- Follow the exact call flow below. Do not deviate.
- Do NOT ask about "replacement".
- Ask ONE closing question ONLY (confirmation of receipt).
- If they confirm, thank them and end the call.
- If they do not confirm / wrong person, ask them to pass it on, then end the call.
- Keep turns short: 1 sentence per turn.
- Do not ask open-ended questions.
- End the call after goodbye. Never speak again.

CALL FLOW (STRICT):
A) Greeting: "Hello, is this <employer_name>?"
B) Identify: "My name is Calleroo, an AI assistant calling on behalf of <caller_name> using the Calleroo mobile app."
C) Message: "<caller_name> is unwell and won't be able to attend their shift on <shift_date> starting at <shift_start_time>."
D) Closing confirmation (ONCE): "Could you please confirm you've received that message?"
E) If YES: "Thank you. Goodbye."
   If NO / unsure / wrong person: "No worries—could you please pass this message on? Thank you. Goodbye."
F) After goodbye, never speak again.
"""

PHONE_AGENT_SYSTEM_PROMPT = """You are Calleroo, a calm, professional phone assistant making an outbound call on behalf of a customer.

STYLE:
- Speak naturally in Australian English.
- Use 1–2 short sentences max per turn.
- Ask only ONE question at a time.
- Be polite, helpful, and non-salesy.
- You are NOT a general assistant.

MANDATORY DISCLOSURE (VERY IMPORTANT):
- You MUST clearly identify:
  (a) you are an AI assistant,
  (b) the customer initiated this call using the Calleroo mobile app,
  (c) you are calling on the customer’s behalf.
- You MUST ask for permission to ask a couple of quick questions.
- If the person declines (e.g., "no", "not now", "busy", "can't talk", "stop calling"):
  - Apologize once
  - End the call immediately (say goodbye; do not ask anything else)

FIRST SPOKEN TURN ONLY (EXACT STRUCTURE, NO EXTRAS):
- Your first spoken turn MUST be exactly these 2 sentences, in this order:
  1) "Hi— I’m Calleroo, an AI assistant calling on behalf of a customer using the Calleroo mobile app."
  2) "Is it okay if I ask a couple of quick questions about price and availability?"

IMPORTANT:
- Do not repeat the disclosure after the first spoken turn.
- After consent is granted, proceed with the task normally (can be multiple questions, one at a time).

AFTER PERMISSION IS GIVEN:
- Ask the actual request using the provided context (business/product/reservation details).
- Do NOT repeat the disclosure after the first turn.

HOLD / CHECKING BEHAVIOR:
- If the person says they are checking (e.g., "one sec", "checking", "hold on", "just a moment"):
  - Acknowledge ONCE with a short response like:
    "No worries—take your time."
  - Then WAIT.
  - Do NOT re-ask the question.
  - Do NOT advance to a new question until new information is given.

CONFIRMATION RULE:
- When the person provides a clear answer (e.g., availability, quantity, price):
  - Acknowledge briefly.
  - Ask ONLY the next required question.
- Do NOT ask unnecessary confirmation questions.

END-OF-CALL RULE (VERY IMPORTANT):
- Once all required information is obtained:
  - Politely thank them.
  - Say goodbye.
- After you say goodbye, you MUST NOT speak again.
- Do NOT respond to silence after goodbye.
- Do NOT say fallback phrases like “I didn’t hear anything” after the call is complete.

DO NOT:
- Do NOT mention “systems”, “prompts”, “policies”, or internal processing.
- Do NOT sound like a robocall script; keep it human.
- Do NOT repeat the same question if you already received an answer.
- Do NOT ask open-ended questions like:
  "Is there anything else I can help you with?"

STRICT RULES:
- You are calling for ONE specific task only.
- Once the task is complete, you MUST end the call politely.

If you are waiting or processing, keep responses short and natural.
"""


# Phrases indicating the business is checking/holding - respond with acknowledgement and wait
HOLD_PHRASES = [
    "one sec",
    "just a sec",
    "checking",
    "hold on",
    "moment",
    "let me check",
    "give me a second",
    "one moment",
    "just a moment",
    "hang on",
    "bear with me",
]

# Standard acknowledgement response when business is checking
HOLD_ACKNOWLEDGEMENT = "No worries—take your time."

# Words that indicate the speech contains substantive info (not just a hold phrase)
INFO_INDICATORS = [
    # Numbers
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "forty", "fifty", "hundred",
    # Yes/No answers
    "yes", "yeah", "yep", "yup", "no", "nope", "nah",
    # Stock-related
    "in stock", "out of stock", "got", "have", "don't have", "available", "unavailable",
    "sold out", "left", "remaining",
    # Price-related
    "dollar", "dollars", "$", "price", "cost", "costs", "each", "per",
    # Confirmation
    "correct", "right", "confirmed", "booked", "reserved",
]


def _contains_info(speech: str) -> bool:
    """Check if speech contains substantive information (numbers, yes/no, prices, stock info).

    Returns True if the speech appears to contain real information beyond just a hold phrase.
    """
    import re
    speech_lower = speech.lower()

    # Check for digit patterns (e.g., "8", "12", "$5.99")
    if re.search(r'\d', speech):
        return True

    # Check for info indicator words
    for indicator in INFO_INDICATORS:
        if indicator in speech_lower:
            return True

    return False


# ============================================================
# SICK_CALLER: YES/NO/PASS-ON Detection Helpers
# ============================================================

NEGATIVE_ANSWERS = [
    "no", "nope", "nah", "not needed", "don't need", "do not need", "all good",
    "we're fine", "no thanks", "can't", "cannot", "not really"
]

POSITIVE_ANSWERS = [
    "yes", "yeah", "yep", "sure", "ok", "okay", "got it", "received",
    "understood", "will do", "noted", "thanks", "thank you"
]

PASS_ON_PHRASES = [
    "not me", "wrong person", "not the manager", "not sure", "can't help",
    "speak to", "call back", "pass it on", "i'll tell", "i can tell",
    "let them know", "i will let", "send to", "wrong number", "who is this",
    "i'm not", "im not", "that's not me"
]


def _detect_yes_no(speech: str) -> Optional[str]:
    """Detect if speech is a YES or NO answer.

    Returns "YES", "NO", or None if unclear.
    """
    s = speech.lower().strip()

    # Check negative first (more important to catch)
    if any(p in s for p in NEGATIVE_ANSWERS):
        return "NO"

    # Check positive
    if any(p in s for p in POSITIVE_ANSWERS):
        return "YES"

    return None


def _detect_pass_on(speech: str) -> bool:
    """Detect if user is indicating they're the wrong person or can't help.

    Returns True if speech suggests passing on the message.
    """
    s = speech.lower().strip()
    return any(p in s for p in PASS_ON_PHRASES)


def _is_pure_hold_phrase(speech: str) -> bool:
    """Check if speech is purely a hold phrase without substantive info.

    Only returns True if:
    - Speech is short (< 8 words) OR matches a hold phrase
    - AND speech does NOT contain numbers, prices, yes/no, or stock info

    This prevents "eating" responses like "Yeah one sec, we have eight"
    """
    speech_lower = speech.lower().strip()
    word_count = len(speech_lower.split())

    # First check if it contains any real info - if so, NOT a pure hold
    if _contains_info(speech):
        return False

    # Check if it contains a hold phrase
    has_hold_phrase = any(phrase in speech_lower for phrase in HOLD_PHRASES)

    if not has_hold_phrase:
        return False

    # It's a pure hold if it's short OR mostly just the hold phrase
    # Short = less than 8 words
    if word_count < 8:
        return True

    # For longer utterances, only treat as hold if it's very minimal content
    # (just the hold phrase with maybe filler words)
    return False


class TwilioService:
    """Service for managing Twilio outbound calls."""

    def __init__(self):
        """Initialize Twilio client.

        Does NOT crash if Twilio not configured - allows graceful degradation.
        Endpoints will return 503 if Twilio not configured.
        """
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")
        self.webhook_base_url = os.getenv("WEBHOOK_BASE_URL", "")

        self.client: Optional[TwilioClient] = None
        self.openai_client: Optional[AsyncOpenAI] = None

        # Check if Twilio is configured
        if self.account_sid and self.auth_token and self.phone_number:
            self.client = TwilioClient(self.account_sid, self.auth_token)
            logger.info(f"TwilioService configured with phone: {self.phone_number}")
        else:
            logger.warning("TwilioService: Twilio credentials not configured - calls will fail")

        # OpenAI for transcription and outcome analysis
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            self.openai_client = AsyncOpenAI(api_key=openai_key)
            self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            logger.info(f"TwilioService OpenAI configured with model: {self.openai_model}")
        else:
            logger.warning("TwilioService: OpenAI not configured - transcription/analysis will fail")

    @property
    def is_configured(self) -> bool:
        """Check if Twilio is properly configured."""
        return self.client is not None

    def start_call(
        self,
        conversation_id: str,
        agent_type: str,
        phone_e164: str,
        script_preview: str,
        slots: Dict[str, Any],
    ) -> CallRun:
        """Start an outbound call via Twilio.

        Args:
            conversation_id: Current conversation ID
            agent_type: Agent type (STOCK_CHECKER, RESTAURANT_RESERVATION)
            phone_e164: Phone number in E.164 format
            script_preview: The script to speak during the call
            slots: Collected conversation slots

        Returns:
            CallRun with Twilio Call SID

        Raises:
            RuntimeError: If Twilio not configured
            Exception: If Twilio API call fails
        """
        if not self.is_configured:
            raise RuntimeError("Twilio not configured")

        if not self.webhook_base_url:
            raise RuntimeError("WEBHOOK_BASE_URL not configured - required for Twilio webhooks")

        # Build webhook URLs
        voice_url = f"{self.webhook_base_url}/twilio/voice?conversationId={conversation_id}"
        status_callback = f"{self.webhook_base_url}/twilio/status"

        logger.info(f"Starting Twilio call to {phone_e164} for conversation {conversation_id}")

        # Create call via Twilio
        call = self.client.calls.create(
            to=phone_e164,
            from_=self.phone_number,
            url=voice_url,
            status_callback=status_callback,
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            record=True,  # Record the call for transcription
            recording_status_callback=f"{self.webhook_base_url}/twilio/recording",
            recording_status_callback_event=["completed"],
        )

        # Create CallRun
        call_run = CallRun(
            call_id=call.sid,
            conversation_id=conversation_id,
            agent_type=agent_type,
            phone_e164=phone_e164,
            script_preview=script_preview,
            slots=slots,
            status=call.status,
        )

        # Store in memory
        CALL_RUNS[call.sid] = call_run

        logger.info(f"Twilio call started: SID={call.sid}, status={call.status}")
        return call_run

    def get_call_run(self, call_id: str) -> Optional[CallRun]:
        """Get a call run by ID."""
        return CALL_RUNS.get(call_id)

    def generate_twiml(self, conversation_id: str) -> str:
        """Generate TwiML for the call.

        Args:
            conversation_id: Conversation ID to look up script

        Returns:
            TwiML XML string
        """
        # Find the call run by conversation_id
        call_run = None
        for run in CALL_RUNS.values():
            if run.conversation_id == conversation_id:
                call_run = run
                break

        if call_run:
            script = call_run.script_preview
        else:
            script = "Hello, this is Calleroo. I apologize, but there was a technical issue. Please have a nice day."
            logger.warning(f"No call run found for conversation {conversation_id}")

        # Build TwiML with Australian English voice
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew" language="en-AU">{self._escape_xml(script)}</Say>
    <Pause length="2"/>
    <Say voice="Polly.Matthew" language="en-AU">Thank you for your time. Goodbye.</Say>
</Response>"""

        return twiml

    def update_status(self, call_id: str, status: str, duration: Optional[int] = None) -> None:
        """Update call status from Twilio webhook.

        Args:
            call_id: Twilio Call SID
            status: New status
            duration: Call duration in seconds (if completed)
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"update_status: Unknown call_id {call_id}")
            return

        call_run.status = status
        if duration is not None:
            call_run.duration_seconds = duration

        # OPTIONAL: Fetch call cost when completed (may not be immediately available)
        if status == "completed" and self.client:
            try:
                call = self.client.calls(call_id).fetch()
                if getattr(call, "price", None) is not None:
                    call_run.cost = abs(float(call.price))
                    call_run.cost_currency = call.price_unit or "USD"
                    logger.info(f"Call {call_id} cost: {call_run.cost} {call_run.cost_currency}")
            except Exception as e:
                logger.warning(f"Failed to fetch cost for call {call_id}: {e}")

        logger.info(f"Call {call_id} status updated to {status}")

    def set_recording_url(self, call_id: str, recording_url: str) -> None:
        """Store recording URL for a call.

        Args:
            call_id: Twilio Call SID
            recording_url: URL to the recording
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"set_recording_url: Unknown call_id {call_id}")
            return

        call_run.recording_url = recording_url
        logger.info(f"Call {call_id} recording URL stored")

    async def transcribe_recording(self, call_id: str) -> Optional[str]:
        """Transcribe a call recording using OpenAI Whisper.

        Args:
            call_id: Twilio Call SID

        Returns:
            Transcript text or None if failed
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"transcribe_recording: Unknown call_id {call_id}")
            return None

        if not call_run.recording_url:
            logger.warning(f"transcribe_recording: No recording URL for call {call_id}")
            return None

        if not self.openai_client:
            logger.error("transcribe_recording: OpenAI not configured")
            return None

        try:
            # Download recording from Twilio
            # Twilio recording URLs need auth
            recording_url = f"{call_run.recording_url}.mp3"

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    recording_url,
                    auth=(self.account_sid, self.auth_token),
                    follow_redirects=True
                )
                response.raise_for_status()
                audio_data = response.content

            # Write to temp file for Whisper
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name

            try:
                # Transcribe with Whisper
                with open(temp_path, "rb") as audio_file:
                    transcript_response = await self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="en"
                    )

                transcript = transcript_response.text
                call_run.transcript = transcript
                logger.info(f"Call {call_id} transcribed: {len(transcript)} chars")
                return transcript

            finally:
                # Clean up temp file
                import os as os_module
                os_module.unlink(temp_path)

        except Exception as e:
            logger.error(f"transcribe_recording failed for call {call_id}: {e}")
            call_run.error = f"Transcription failed: {str(e)}"
            return None

    async def analyze_outcome(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Analyze call outcome using OpenAI.

        Uses the event transcript (live_transcript) as the primary source for
        determining who said what. The Whisper transcript is included as
        optional supplementary information but should not be trusted for
        speaker attribution.

        Args:
            call_id: Twilio Call SID

        Returns:
            Outcome dict or None if failed
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"analyze_outcome: Unknown call_id {call_id}")
            return None

        # Build event transcript from live_transcript (this is the authoritative source)
        event_transcript = "\n".join(call_run.live_transcript) if call_run.live_transcript else ""

        # We can proceed with just the event transcript, Whisper is optional
        if not event_transcript and not call_run.transcript:
            logger.warning(f"analyze_outcome: No transcript available for call {call_id}")
            return None

        if not self.openai_client:
            logger.error("analyze_outcome: OpenAI not configured")
            return None

        try:
            # Build raw transcript section (optional, for supplementary context)
            if call_run.transcript:
                raw_transcript_section = f"""RAW AUDIO TRANSCRIPT (supplementary - may have speaker attribution errors):
{call_run.transcript}"""
            else:
                raw_transcript_section = "(No raw audio transcript available)"

            # Build prompt with event transcript as primary source
            prompt = OUTCOME_ANALYSIS_PROMPT.format(
                agent_type=call_run.agent_type,
                script_preview=call_run.script_preview,
                slots=json.dumps(call_run.slots),
                event_transcript=event_transcript if event_transcript else "(No event transcript recorded)",
                raw_transcript_section=raw_transcript_section
            )

            response = await self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are an AI that analyzes phone call transcripts."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            if not content:
                logger.error(f"analyze_outcome: Empty response for call {call_id}")
                return None

            logger.info(f"analyze_outcome raw content for {call_id}: {content[:500]}")

            try:
                outcome = json.loads(content)
                # Validate expected keys exist
                if "success" not in outcome:
                    logger.warning(f"analyze_outcome: Missing 'success' key for {call_id}, keys={list(outcome.keys())}")
                    outcome["success"] = False
                if "summary" not in outcome:
                    outcome["summary"] = "Call completed"
                if "extractedFacts" not in outcome:
                    outcome["extractedFacts"] = {}
                if "confidence" not in outcome:
                    outcome["confidence"] = "MEDIUM"
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"analyze_outcome: JSON parse failed for call {call_id}: {e}, content={content[:200]}")
                # Fallback - try to extract success from content
                outcome = {
                    "success": "success" in content.lower() and "true" in content.lower(),
                    "summary": "Call completed, analysis parsing failed",
                    "extractedFacts": {},
                    "confidence": "LOW"
                }

            call_run.outcome = outcome
            logger.info(f"Call {call_id} outcome analyzed: success={outcome.get('success')}")
            return outcome

        except Exception as e:
            logger.error(f"analyze_outcome failed for call {call_id}: {type(e).__name__}: {e}")
            # Still try to set a fallback outcome
            call_run.outcome = {
                "success": False,
                "summary": f"Analysis failed: {type(e).__name__}",
                "extractedFacts": {},
                "confidence": "LOW"
            }
            call_run.error = f"Outcome analysis failed: {str(e)}"
            return call_run.outcome

    async def process_completed_call(self, call_id: str) -> None:
        """Process a completed call: transcribe and analyze.

        Called when Twilio reports call completed.

        Args:
            call_id: Twilio Call SID
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"process_completed_call: Unknown call_id {call_id}")
            return

        logger.info(f"Processing completed call {call_id}")

        # Wait for recording if not yet available
        if not call_run.recording_url:
            logger.info(f"Call {call_id}: Waiting for recording URL...")
            # Recording webhook should set this
            return

        # Transcribe
        transcript = await self.transcribe_recording(call_id)
        if not transcript:
            logger.warning(f"Call {call_id}: Transcription failed or no audio")
            return

        # Analyze outcome
        await self.analyze_outcome(call_id)

    def _escape_xml(self, text: str) -> str:
        """Escape text for XML."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _extract_question(self, text: str) -> Optional[str]:
        """Extract the question portion from a response (text ending with ?).

        Returns the question text or None if no question found.
        """
        if "?" not in text:
            return None

        # Find the last sentence ending with ?
        sentences = text.replace("!", ".").replace("?", "?.").split(".")
        for sentence in reversed(sentences):
            sentence = sentence.strip()
            if sentence.endswith("?"):
                return sentence
        return None

    def _is_same_question(self, q1: str, q2: str) -> bool:
        """Check if two questions are substantially the same.

        Uses normalized comparison (lowercase, stripped punctuation, key words).
        """
        import re

        def normalize(q: str) -> str:
            # Lowercase, remove punctuation, normalize whitespace
            q = q.lower()
            q = re.sub(r'[^\w\s]', '', q)
            q = ' '.join(q.split())
            return q

        n1 = normalize(q1)
        n2 = normalize(q2)

        # Exact match after normalization
        if n1 == n2:
            return True

        # Check word overlap (if 80%+ words match, consider same question)
        words1 = set(n1.split())
        words2 = set(n2.split())
        if not words1 or not words2:
            return False

        intersection = words1 & words2
        union = words1 | words2
        overlap = len(intersection) / len(union) if union else 0

        return overlap >= 0.8

    async def generate_agent_response(
        self,
        call_run: CallRun,
        user_speech: str,
    ) -> str:
        """Generate next agent response using OpenAI.

        Args:
            call_run: The current call run state
            user_speech: What the user just said

        Returns:
            Plain text response for the agent to speak
        """
        if not self.openai_client:
            logger.error("generate_agent_response: OpenAI not configured")
            return "I'm sorry, I'm having technical difficulties. Please try again later."

        # ============================================================
        # SICK_CALLER: Deterministic guard BEFORE calling OpenAI
        # If we've already asked for confirmation, force a terminal response
        # ============================================================
        if call_run.agent_type == "SICK_CALLER" and call_run.message_confirm_asked:
            # Check for pass-on indicators first (wrong person)
            if _detect_pass_on(user_speech):
                call_run.message_confirm_result = "PASS_ON"
                call_run.is_terminal = True
                logger.info(f"SICK_CALLER: Pass-on detected, ending call. Speech: {user_speech[:50]}...")
                return "No worries—could you please pass this message on? Thank you. Goodbye."

            # Check for YES/NO
            yn = _detect_yes_no(user_speech)
            if yn == "YES":
                call_run.message_confirm_result = "YES"
                call_run.is_terminal = True
                logger.info(f"SICK_CALLER: Confirmation received (YES), ending call. Speech: {user_speech[:50]}...")
                return "Thank you. Goodbye."
            if yn == "NO":
                call_run.message_confirm_result = "NO"
                call_run.is_terminal = True
                logger.info(f"SICK_CALLER: Confirmation negative (NO), ending call. Speech: {user_speech[:50]}...")
                return "No worries—could you please pass this message on? Thank you. Goodbye."

            # If unclear, let OpenAI handle but still constrained by prompt
            logger.info(f"SICK_CALLER: Confirmation asked but response unclear, letting LLM handle: {user_speech[:50]}...")

        try:
            # Build conversation history from live_transcript
            transcript_text = "\n".join(call_run.live_transcript)

            # ============================================================
            # Select system prompt by agent_type
            # ============================================================
            system_prompt = PHONE_AGENT_SYSTEM_PROMPT

            if call_run.agent_type == "SICK_CALLER":
                # Use SICK_CALLER specific prompt with slot values injected
                employer_name = str(call_run.slots.get("employer_name", "your workplace"))
                caller_name = str(call_run.slots.get("caller_name", "the customer"))
                shift_date = str(call_run.slots.get("shift_date", "your shift date"))
                shift_start_time = str(call_run.slots.get("shift_start_time", "your shift time"))

                system_prompt = (SICK_CALLER_PHONE_AGENT_PROMPT
                    .replace("<employer_name>", employer_name)
                    .replace("<caller_name>", caller_name)
                    .replace("<shift_date>", shift_date)
                    .replace("<shift_start_time>", shift_start_time)
                )

                logger.info(f"SICK_CALLER: Using dedicated prompt with slots: employer={employer_name}, caller={caller_name}")

            # Build user message with context
            user_message = f"""Conversation so far:
{transcript_text}

Context:
Agent type: {call_run.agent_type}
Objective: {call_run.script_preview}
Slots: {json.dumps(call_run.slots)}

Latest user said:
"{user_speech}"

What should you say next?"""

            response = await self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=150,
            )

            content = response.choices[0].message.content
            if not content:
                logger.error("generate_agent_response: Empty response from OpenAI")
                return "I'm sorry, could you repeat that?"

            # Clean up response (remove quotes if present)
            content = content.strip().strip('"').strip("'")

            # ============================================================
            # SICK_CALLER: Mark confirmation asked if LLM asked it
            # ============================================================
            if call_run.agent_type == "SICK_CALLER":
                content_lower = content.lower()
                if ("confirm" in content_lower and "received" in content_lower) or \
                   ("confirm" in content_lower and "message" in content_lower) or \
                   "is that okay" in content_lower or \
                   "did you get that" in content_lower:
                    call_run.message_confirm_asked = True
                    logger.info(f"SICK_CALLER: Marked message_confirm_asked=True. Response: {content[:50]}...")

                # Detect goodbye - mark terminal
                if "goodbye" in content_lower or "good bye" in content_lower:
                    call_run.is_terminal = True
                    logger.info(f"SICK_CALLER: Goodbye detected, marked terminal. Response: {content[:50]}...")

            # Deterministic guard: prevent repeating the same question (non-SICK_CALLER)
            # For SICK_CALLER, the deterministic guard above handles this
            if call_run.agent_type != "SICK_CALLER":
                # But ALLOW repeat if user provided new info (numbers, yes/no, prices)
                new_question = self._extract_question(content)
                if new_question and call_run.last_question:
                    # Check if it's substantially the same question (case-insensitive, normalized)
                    if self._is_same_question(new_question, call_run.last_question):
                        # Only block if user speech didn't contain new info
                        user_provided_info = _contains_info(user_speech)
                        if not user_provided_info:
                            logger.warning(f"Detected repeat question without new user info, replacing with wait acknowledgement. Original: {content[:50]}...")
                            content = "No worries—take your time. Let me know when you're ready."
                            # Don't update last_question since we're not asking a new one
                        else:
                            # User provided info, so this is likely a legitimate follow-up
                            # Allow it through and update last_question
                            logger.info(f"Allowing similar question because user provided new info: {user_speech[:50]}...")
                            call_run.last_question = new_question
                    else:
                        # Different question - update last_question
                        call_run.last_question = new_question
                elif new_question:
                    # First question - store it
                    call_run.last_question = new_question

            logger.info(f"Agent response generated: {content[:100]}...")
            return content

        except Exception as e:
            logger.error(f"generate_agent_response failed: {e}")
            return "I'm sorry, I'm having trouble. Could you repeat that?"

    async def generate_agent_response_async(self, call_id: str, user_speech: str) -> None:
        """Generate agent response in background for filler/poll pattern.

        This method is designed to be run as a background task. It:
        1. Looks up call_run by call_id (Twilio SID)
        2. Sets is_generating=True and stores pending_user_speech
        3. Calls the existing generate_agent_response() method
        4. Stores result in pending_agent_reply
        5. Sets is_generating=False

        Args:
            call_id: Twilio Call SID
            user_speech: What the user just said
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.error(f"generate_agent_response_async: Unknown call_id {call_id}")
            return

        if not self.openai_client:
            logger.error("generate_agent_response_async: OpenAI not configured")
            return

        if call_run.is_generating:
            logger.warning(f"generate_agent_response_async: Already generating for {call_id}")
            return

        # Mark as generating
        call_run.is_generating = True
        start_time = datetime.utcnow()
        call_run.pending_started_at = start_time
        call_run.pending_user_speech = user_speech
        call_run.pending_agent_reply = None
        logger.info(f"[TIMING] OpenAI generation started at {start_time.isoformat()} for call {call_id}")

        try:
            # Call the existing method
            reply = await self.generate_agent_response(call_run, user_speech)
            call_run.pending_agent_reply = reply
            end_time = datetime.utcnow()
            elapsed_ms = (end_time - start_time).total_seconds() * 1000
            logger.info(f"[TIMING] OpenAI generation completed at {end_time.isoformat()} ({elapsed_ms:.0f}ms) for call {call_id}: {reply[:50]}...")
        except Exception as e:
            logger.error(f"generate_agent_response_async failed for {call_id}: {e}")
            call_run.error = f"agent_generate_failed: {str(e)}"
            call_run.pending_agent_reply = "Sorry, one moment. Could you repeat that?"
        finally:
            call_run.is_generating = False


# Singleton instance (created lazily)
_twilio_service: Optional[TwilioService] = None


def get_twilio_service() -> TwilioService:
    """Get or create the TwilioService singleton."""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service
