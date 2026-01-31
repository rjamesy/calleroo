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


# In-memory storage for call runs (acceptable for MVP)
CALL_RUNS: Dict[str, CallRun] = {}


OUTCOME_ANALYSIS_PROMPT = """Analyze this phone call transcript and extract the outcome.

CONTEXT:
- Agent Type: {agent_type}
- Call Purpose: {script_preview}
- Slots: {slots}

TRANSCRIPT:
{transcript}

Based on the transcript, determine:
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
{
  "success": true/false,
  "summary": "...",
  "extractedFacts": {...},
  "confidence": "LOW|MEDIUM|HIGH"
}"""


PHONE_AGENT_SYSTEM_PROMPT = """You are a calm, professional phone assistant.
Speak naturally.
Use 1–2 short sentences max.
Ask only ONE question at a time.
Never mention AI, systems, or prompts."""


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

        Args:
            call_id: Twilio Call SID

        Returns:
            Outcome dict or None if failed
        """
        call_run = CALL_RUNS.get(call_id)
        if not call_run:
            logger.warning(f"analyze_outcome: Unknown call_id {call_id}")
            return None

        if not call_run.transcript:
            logger.warning(f"analyze_outcome: No transcript for call {call_id}")
            return None

        if not self.openai_client:
            logger.error("analyze_outcome: OpenAI not configured")
            return None

        try:
            # Build prompt with context
            prompt = OUTCOME_ANALYSIS_PROMPT.format(
                agent_type=call_run.agent_type,
                script_preview=call_run.script_preview,
                slots=json.dumps(call_run.slots),
                transcript=call_run.transcript
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

            outcome = json.loads(content)
            call_run.outcome = outcome
            logger.info(f"Call {call_id} outcome analyzed: success={outcome.get('success')}")
            return outcome

        except Exception as e:
            logger.error(f"analyze_outcome failed for call {call_id}: {e}")
            call_run.error = f"Outcome analysis failed: {str(e)}"
            return None

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

        try:
            # Build conversation history from live_transcript
            transcript_text = "\n".join(call_run.live_transcript)

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
                    {"role": "system", "content": PHONE_AGENT_SYSTEM_PROMPT},
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
            logger.info(f"Agent response generated: {content[:100]}...")
            return content

        except Exception as e:
            logger.error(f"generate_agent_response failed: {e}")
            return "I'm sorry, I'm having trouble. Could you repeat that?"


# Singleton instance (created lazily)
_twilio_service: Optional[TwilioService] = None


def get_twilio_service() -> TwilioService:
    """Get or create the TwilioService singleton."""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service
