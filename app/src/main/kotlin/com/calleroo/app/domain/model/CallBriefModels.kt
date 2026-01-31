package com.calleroo.app.domain.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * Place information for call brief request.
 */
@Serializable
data class CallBriefPlace(
    val placeId: String,
    val businessName: String,
    val formattedAddress: String? = null,
    val phoneE164: String
)

/**
 * User disclosure settings for the call.
 */
@Serializable
data class CallBriefDisclosure(
    val nameShare: Boolean = false,
    val phoneShare: Boolean = false
)

/**
 * Fallback behaviors during the call (agent-specific).
 */
@Serializable
data class CallBriefFallbacks(
    // Stock Checker fallbacks
    val askETA: Boolean? = null,
    val askNearestStore: Boolean? = null,
    // Restaurant reservation fallbacks
    val retryIfNoAnswer: Boolean? = null,
    val retryIfBusy: Boolean? = null,
    val leaveVoicemail: Boolean? = null
)

/**
 * Request to generate a call brief.
 * Used with POST /call/brief endpoint.
 */
@Serializable
data class CallBriefRequestV2(
    val conversationId: String,
    val agentType: String, // "STOCK_CHECKER" or "RESTAURANT_RESERVATION"
    val place: CallBriefPlace,
    val slots: JsonObject,
    val disclosure: CallBriefDisclosure = CallBriefDisclosure(),
    val fallbacks: CallBriefFallbacks = CallBriefFallbacks(),
    val debug: Boolean = false
)

/**
 * Response containing the call brief.
 */
@Serializable
data class CallBriefResponseV2(
    val objective: String, // Short description of call goal
    val scriptPreview: String, // Plain text, multi-line, no markdown
    val confirmationChecklist: List<String>, // 2-6 items user should verify
    val normalizedPhoneE164: String, // Validated/normalized phone
    val requiredFieldsMissing: List<String>, // Empty if all required fields present
    val aiCallMade: Boolean,
    val aiModel: String
)

/**
 * Request to start a call (stub in Step 3).
 * Used with POST /call/start/v2 endpoint.
 */
@Serializable
data class CallStartRequestV2(
    val conversationId: String,
    val agentType: String,
    val placeId: String,
    val phoneE164: String,
    val slots: JsonObject
)

/**
 * Response from call start (stub in Step 3).
 */
@Serializable
data class CallStartResponseV2(
    val status: String, // "NOT_IMPLEMENTED" in Step 3
    val message: String
)

// ============================================================
// Call Start V3 Models (Step 4 - Real Twilio Calls)
// ============================================================

/**
 * Request to start a real Twilio call.
 * Used with POST /call/start endpoint.
 */
@Serializable
data class CallStartRequestV3(
    val conversationId: String,
    val agentType: String,
    val placeId: String,
    val phoneE164: String,
    val slots: JsonObject,
    val scriptPreview: String // The generated script to speak
)

/**
 * Response with real Twilio call ID.
 */
@Serializable
data class CallStartResponseV3(
    val callId: String, // Twilio Call SID
    val status: String, // "queued", "ringing", etc.
    val message: String
)

/**
 * Response from GET /call/status/{callId}.
 */
@Serializable
data class CallStatusResponseV1(
    val callId: String,
    val status: String, // queued, ringing, in-progress, completed, failed, busy, no-answer
    val durationSeconds: Int? = null,
    val transcript: String? = null,
    val outcome: JsonObject? = null, // OpenAI analysis
    val error: String? = null
) {
    /**
     * Check if this is a terminal status (call is finished).
     */
    val isTerminal: Boolean
        get() = status in listOf("completed", "failed", "busy", "no-answer", "canceled")
}

// ============================================================
// Call Result Format Models (Post-call summary formatting)
// ============================================================

/**
 * Request to format call results for display.
 * Used with POST /call/result/format endpoint.
 */
@Serializable
data class CallResultFormatRequestV1(
    val agentType: String,
    val callId: String,
    val status: String,
    val durationSeconds: Int? = null,
    val transcript: String? = null,
    val outcome: JsonObject? = null,
    val error: String? = null
)

/**
 * Formatted call results for UI display.
 */
@Serializable
data class CallResultFormatResponseV1(
    val title: String, // e.g. "Call completed"
    val bullets: List<String>, // short bullet points (max 8)
    val extractedFacts: JsonObject = JsonObject(emptyMap()), // pass-through from outcome
    val nextSteps: List<String>, // 1-4 action items
    val formattedTranscript: String? = null,
    val aiCallMade: Boolean,
    val aiModel: String
)
