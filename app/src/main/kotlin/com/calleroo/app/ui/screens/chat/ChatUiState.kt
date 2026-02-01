package com.calleroo.app.ui.screens.chat

import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.ConfirmationCard
import com.calleroo.app.domain.model.NextAction
import com.calleroo.app.domain.model.PlaceSearchParams
import com.calleroo.app.domain.model.Question
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject

/**
 * Represents a single message in the chat UI.
 */
data class ChatMessageUi(
    val id: String,
    val content: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis()
)

/**
 * UI State for the UnifiedChatScreen.
 *
 * IMPORTANT: This state is ONLY populated from backend responses.
 * The Android client does NOT decide questions, slots, or flow order.
 */
data class ChatUiState(
    val conversationId: String = "",
    val agentType: AgentType = AgentType.STOCK_CHECKER,
    val messages: List<ChatMessageUi> = emptyList(),
    val slots: JsonObject = buildJsonObject {},
    val currentQuestion: Question? = null,
    val confirmationCard: ConfirmationCard? = null,
    val confirmationCardId: String? = null,  // Stable ID for idempotency
    val nextAction: NextAction? = null,
    val isLoading: Boolean = false,
    val isConfirmationSubmitting: Boolean = false,  // True while awaiting CONFIRM/REJECT response
    val error: String? = null,
    val isComplete: Boolean = false,
    val placeSearchParams: PlaceSearchParams? = null
) {
    val showConfirmationCard: Boolean
        get() = nextAction == NextAction.CONFIRM && confirmationCard != null

    /**
     * Show Continue button when:
     * - COMPLETE: Conversation is done, proceed to CallSummary (for agents without place search)
     * - FIND_PLACE: Backend wants to navigate to place search with placeSearchParams
     *
     * For FIND_PLACE, this acts as a manual trigger if auto-navigation didn't fire.
     * For COMPLETE, this is the primary way to proceed (e.g., SICK_CALLER where phone is known).
     */
    val showContinueButton: Boolean
        get() = (nextAction == NextAction.COMPLETE && isComplete) ||
                (nextAction == NextAction.FIND_PLACE && placeSearchParams != null)
}
