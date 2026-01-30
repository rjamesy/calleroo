package com.calleroo.app.ui.screens.callstatus

import kotlinx.serialization.json.JsonObject

/**
 * State machine for Call Status screen (Screen 5).
 *
 * State transitions:
 * - Polling (initial) - actively checking call status
 * - Polling -> Completed (call finished successfully with transcript/outcome)
 * - Polling -> Failed (call ended with failure status)
 * - Polling -> Failed (polling timeout exceeded)
 */
sealed class CallStatusState {

    /**
     * Actively polling for call status updates.
     */
    data class Polling(
        val callId: String,
        val status: String = "queued",
        val pollCount: Int = 0
    ) : CallStatusState() {
        /**
         * User-friendly status message.
         */
        val statusMessage: String
            get() = when (status) {
                "queued" -> "Waiting to connect..."
                "ringing" -> "Ringing..."
                "in-progress" -> "Call in progress..."
                else -> "Processing..."
            }
    }

    /**
     * Call completed successfully with results.
     */
    data class Completed(
        val callId: String,
        val durationSeconds: Int,
        val transcript: String?,
        val outcome: CallOutcome?
    ) : CallStatusState() {
        /**
         * Formatted duration string.
         */
        val formattedDuration: String
            get() {
                val minutes = durationSeconds / 60
                val seconds = durationSeconds % 60
                return if (minutes > 0) {
                    "${minutes}m ${seconds}s"
                } else {
                    "${seconds}s"
                }
            }
    }

    /**
     * Call ended with a failure status.
     */
    data class Failed(
        val callId: String,
        val status: String,
        val error: String?
    ) : CallStatusState() {
        /**
         * User-friendly error message.
         */
        val errorMessage: String
            get() = when (status) {
                "busy" -> "The line was busy"
                "no-answer" -> "No one answered"
                "failed" -> error ?: "Call failed"
                "canceled" -> "Call was canceled"
                else -> error ?: "An error occurred"
            }
    }
}

/**
 * Parsed call outcome from OpenAI analysis.
 */
data class CallOutcome(
    val success: Boolean,
    val summary: String,
    val extractedFacts: Map<String, Any?>,
    val confidence: String
) {
    companion object {
        /**
         * Parse outcome from JSON object.
         */
        fun fromJson(json: JsonObject?): CallOutcome? {
            if (json == null) return null
            return try {
                CallOutcome(
                    success = json["success"]?.toString()?.toBooleanStrictOrNull() ?: false,
                    summary = json["summary"]?.toString()?.removeSurrounding("\"") ?: "",
                    extractedFacts = parseExtractedFacts(json["extractedFacts"]),
                    confidence = json["confidence"]?.toString()?.removeSurrounding("\"") ?: "LOW"
                )
            } catch (e: Exception) {
                null
            }
        }

        private fun parseExtractedFacts(element: kotlinx.serialization.json.JsonElement?): Map<String, Any?> {
            if (element == null || element !is JsonObject) return emptyMap()
            return element.entries.associate { (key, value) ->
                key to when {
                    value.toString() == "null" -> null
                    value.toString() == "true" -> true
                    value.toString() == "false" -> false
                    value.toString().toIntOrNull() != null -> value.toString().toInt()
                    else -> value.toString().removeSurrounding("\"")
                }
            }
        }
    }
}
