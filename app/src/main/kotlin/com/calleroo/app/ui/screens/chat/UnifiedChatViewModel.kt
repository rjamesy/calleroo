package com.calleroo.app.ui.screens.chat

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.ChatMessage
import com.calleroo.app.domain.model.ClientAction
import com.calleroo.app.domain.model.ConversationResponse
import com.calleroo.app.domain.model.NextAction
import com.calleroo.app.repository.ConversationRepository
import com.calleroo.app.util.UnifiedConversationGuard
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import java.util.UUID
import javax.inject.Inject

@HiltViewModel
class UnifiedChatViewModel @Inject constructor(
    private val conversationRepository: ConversationRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    // Navigation event for Continue button - triggers navigation to PlaceSearch
    private val _navigateToPlaceSearch = MutableStateFlow<Pair<String, String>?>(null)
    val navigateToPlaceSearch: StateFlow<Pair<String, String>?> = _navigateToPlaceSearch.asStateFlow()

    // Navigation event for COMPLETE action - triggers navigation to CallSummary
    private val _navigateToCallSummary = MutableStateFlow(false)
    val navigateToCallSummary: StateFlow<Boolean> = _navigateToCallSummary.asStateFlow()

    private var messageHistory: MutableList<ChatMessage> = mutableListOf()

    companion object {
        private const val TAG = "UnifiedChatViewModel"
        private const val START_TOKEN = "__START__"
    }

    /**
     * Initialize the conversation with given parameters.
     * Immediately calls backend to get the first question.
     */
    fun initialize(agentType: AgentType, conversationId: String) {
        _uiState.update {
            it.copy(
                conversationId = conversationId,
                agentType = agentType
            )
        }

        // Start conversation by requesting the first assistant message (no user bubble/history)
        sendMessage(START_TOKEN)
    }

    /**
     * Send a user message to the backend.
     *
     * CRITICAL: This method does NO local logic.
     * It ONLY posts to /conversation/next and renders the response.
     */
    fun sendMessage(userMessage: String) {
        val isStart = userMessage == START_TOKEN
        if (userMessage.isBlank() && !isStart) return

        // Add user message to UI/history only when not start
        if (!isStart) {
            val userMessageUi = ChatMessageUi(
                id = UUID.randomUUID().toString(),
                content = userMessage,
                isUser = true
            )
            _uiState.update { it.copy(messages = it.messages + userMessageUi) }

            messageHistory.add(ChatMessage(role = "user", content = userMessage))
        }

        _uiState.update {
            it.copy(
                isLoading = true,
                error = null,
                currentQuestion = null,
                confirmationCard = null
            )
        }

        viewModelScope.launch {
            // Always take the latest state for the request (avoid stale snapshot)
            val stateForRequest = _uiState.value

            val outboundMessage = if (isStart) "" else userMessage

            val result = conversationRepository.nextTurn(
                conversationId = stateForRequest.conversationId,
                agentType = stateForRequest.agentType,
                userMessage = outboundMessage,
                slots = stateForRequest.slots,
                messageHistory = messageHistory.toList(),
                debug = true
            )

            result.fold(
                onSuccess = { response ->
                    // CRITICAL: Verify backend drove this response (allows deterministic responses)
                    UnifiedConversationGuard.assertBackendDriven(response.aiCallMade, response.aiModel)

                    // Logging for debugging (non-PII)
                    Log.d(TAG, "Backend response: action=${response.nextAction}, aiModel=${response.aiModel}")
                    Log.d(TAG, "  question.field=${response.question?.field}, inputType=${response.question?.inputType}")
                    Log.d(TAG, "  hasConfirmationCard=${response.confirmationCard != null}, hasPlaceSearchParams=${response.placeSearchParams != null}")

                    // Sanitize response to handle edge cases safely
                    val sanitized = sanitizeResponse(response, stateForRequest.conversationId)

                    val assistantMessageUi = ChatMessageUi(
                        id = UUID.randomUUID().toString(),
                        content = sanitized.assistantMessage,
                        isUser = false
                    )

                    messageHistory.add(ChatMessage(role = "assistant", content = sanitized.assistantMessage))

                    // Merge extracted data into the latest slots (avoid stale merge base)
                    val latestSlots = _uiState.value.slots
                    val newSlots = mergeSlots(latestSlots, sanitized.extractedData)

                    _uiState.update {
                        it.copy(
                            messages = it.messages + assistantMessageUi,
                            slots = newSlots,
                            currentQuestion = sanitized.question,
                            confirmationCard = sanitized.confirmationCard,
                            confirmationCardId = sanitized.confirmationCard?.cardId,
                            nextAction = sanitized.nextAction,
                            isLoading = false,
                            isConfirmationSubmitting = false,
                            isComplete = sanitized.isComplete,
                            placeSearchParams = sanitized.placeSearchParams
                        )
                    }
                },
                onFailure = { throwable ->
                    Log.e(TAG, "Backend error", throwable)
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = throwable.message ?: "Unknown error occurred"
                        )
                    }
                }
            )
        }
    }

    /**
     * Handle confirmation card response.
     * Uses deterministic clientAction to bypass OpenAI and prevent loops.
     * "Yes" sends clientAction=CONFIRM to backend.
     * "Not quite" sends clientAction=REJECT to backend.
     */
    fun handleConfirmation(confirmed: Boolean) {
        val stateSnapshot = _uiState.value

        // Guard: prevent double-submission
        if (stateSnapshot.isConfirmationSubmitting) {
            Log.w(TAG, "handleConfirmation: already submitting, ignoring")
            return
        }

        val clientAction = if (confirmed) ClientAction.CONFIRM else ClientAction.REJECT

        // Generate stable idempotency key from card ID + action
        // If backend doesn't provide cardId, hash the card content
        val cardId = stateSnapshot.confirmationCardId
            ?: stateSnapshot.confirmationCard?.let { generateCardId(it) }
            ?: UUID.randomUUID().toString()
        val actionSuffix = if (confirmed) "CONFIRM" else "REJECT"
        val idempotencyKey = "confirm:${stateSnapshot.conversationId}:$cardId:$actionSuffix"

        Log.d(TAG, "handleConfirmation: confirmed=$confirmed, clientAction=$clientAction, idempotencyKey=$idempotencyKey")

        // Show "Calling..." state - keep card visible but disable buttons
        _uiState.update {
            it.copy(
                isConfirmationSubmitting = true,
                error = null
            )
        }

        viewModelScope.launch {
            val result = conversationRepository.nextTurn(
                conversationId = stateSnapshot.conversationId,
                agentType = stateSnapshot.agentType,
                userMessage = "",  // Empty - clientAction handles the intent
                slots = stateSnapshot.slots,
                messageHistory = messageHistory.toList(),
                debug = true,
                clientAction = clientAction,
                idempotencyKey = idempotencyKey
            )

            result.fold(
                onSuccess = { response ->
                    // Verify backend drove this response (allows deterministic responses)
                    UnifiedConversationGuard.assertBackendDriven(response.aiCallMade, response.aiModel)

                    Log.d(TAG, "Confirmation response: action=${response.nextAction}, aiCallMade=${response.aiCallMade}, aiModel=${response.aiModel}")

                    // Sanitize response
                    val sanitized = sanitizeResponse(response, stateSnapshot.conversationId)

                    val assistantMessageUi = ChatMessageUi(
                        id = UUID.randomUUID().toString(),
                        content = sanitized.assistantMessage,
                        isUser = false
                    )

                    messageHistory.add(ChatMessage(role = "assistant", content = sanitized.assistantMessage))

                    // Merge extracted data into slots (not replace!)
                    val latestSlots = _uiState.value.slots
                    val newSlots = mergeSlots(latestSlots, sanitized.extractedData)

                    _uiState.update {
                        it.copy(
                            messages = it.messages + assistantMessageUi,
                            slots = newSlots,
                            currentQuestion = sanitized.question,
                            confirmationCard = sanitized.confirmationCard,
                            confirmationCardId = sanitized.confirmationCard?.cardId,
                            nextAction = sanitized.nextAction,
                            isLoading = false,
                            isConfirmationSubmitting = false,
                            isComplete = sanitized.isComplete,
                            placeSearchParams = sanitized.placeSearchParams
                        )
                    }
                },
                onFailure = { throwable ->
                    Log.e(TAG, "Confirmation error", throwable)
                    // On error, keep the card visible so user can retry
                    _uiState.update {
                        it.copy(
                            isConfirmationSubmitting = false,
                            error = throwable.message ?: "Unknown error occurred"
                        )
                    }
                }
            )
        }
    }

    /**
     * Generate a stable card ID by hashing the card content.
     * Used for idempotency when backend doesn't provide cardId.
     */
    private fun generateCardId(card: com.calleroo.app.domain.model.ConfirmationCard): String {
        val content = "${card.title}|${card.lines.joinToString("|")}"
        return content.hashCode().toString(16)
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    /**
     * Handle "Continue" button click.
     * Routes to the appropriate screen based on nextAction:
     * - FIND_PLACE: Navigate to PlaceSearch (requires placeSearchParams)
     * - COMPLETE: Navigate to CallSummary (for agents without place search, e.g., SICK_CALLER)
     */
    fun handleContinue() {
        val state = _uiState.value
        when (state.nextAction) {
            NextAction.FIND_PLACE -> {
                val params = state.placeSearchParams
                if (params != null) {
                    Log.i(TAG, "Continue -> PlaceSearch: query=${params.query}, area=${params.area}")
                    _navigateToPlaceSearch.value = Pair(params.query, params.area)
                } else {
                    Log.w(TAG, "Continue clicked but nextAction=FIND_PLACE and placeSearchParams is null")
                }
            }
            NextAction.COMPLETE -> {
                Log.i(TAG, "Continue -> CallSummary: conversationId=${state.conversationId}, agentType=${state.agentType}")
                _navigateToCallSummary.value = true
            }
            else -> {
                Log.w(TAG, "Continue clicked but nextAction=${state.nextAction} not handled")
            }
        }
    }

    /**
     * Clear navigation event after handling.
     */
    fun clearNavigateToPlaceSearch() {
        _navigateToPlaceSearch.value = null
    }

    /**
     * Clear CallSummary navigation event after handling.
     */
    fun clearNavigateToCallSummary() {
        _navigateToCallSummary.value = false
    }

    /**
     * Clear placeSearchParams after navigation to avoid re-navigation.
     */
    fun clearPlaceSearchParams() {
        _uiState.update { it.copy(placeSearchParams = null) }
    }

    /**
     * Merge new extracted data into existing slots.
     */
    private fun mergeSlots(existing: JsonObject, newData: JsonObject?): JsonObject {
        if (newData == null) return existing

        return buildJsonObject {
            existing.forEach { (key, value) -> put(key, value) }
            newData.forEach { (key, value) -> put(key, value) }
        }
    }

    /**
     * Sanitize and validate response from backend.
     * Ensures UI renders a safe model even if backend returns partial/invalid data.
     *
     * Edge cases handled:
     * - Empty assistantMessage -> fallback message
     * - Unknown nextAction -> treat as ASK_QUESTION
     * - FIND_PLACE without placeSearchParams -> show error
     * - ASK_QUESTION without question -> allow freeform input
     * - CONFIRM without confirmationCard -> treat as ASK_QUESTION
     *
     * @param conversationId For traceability in logs
     */
    private fun sanitizeResponse(
        response: ConversationResponse,
        conversationId: String
    ): SanitizedResponse {
        val sanitizationReasons = mutableListOf<String>()

        // Check assistantMessage
        val assistantMessage = if (response.assistantMessage.isBlank()) {
            sanitizationReasons.add("empty_assistant_message")
            "I'm not sure what to say. Please try again."
        } else {
            response.assistantMessage
        }

        // Validate nextAction combinations
        val (sanitizedAction, errorMessage) = when (response.nextAction) {
            NextAction.FIND_PLACE -> {
                if (response.placeSearchParams == null) {
                    sanitizationReasons.add("FIND_PLACE_missing_placeSearchParams")
                    NextAction.ASK_QUESTION to "I need more information before we can search for a place."
                } else {
                    response.nextAction to null
                }
            }
            NextAction.CONFIRM -> {
                if (response.confirmationCard == null) {
                    sanitizationReasons.add("CONFIRM_missing_confirmationCard")
                    NextAction.ASK_QUESTION to null
                } else {
                    response.nextAction to null
                }
            }
            NextAction.ASK_QUESTION -> {
                if (response.question == null) {
                    sanitizationReasons.add("ASK_QUESTION_missing_question")
                    // Don't change action - freeform input is acceptable
                }
                response.nextAction to null
            }
            else -> response.nextAction to null
        }

        // Log sanitization with conversationId for server-side correlation
        if (sanitizationReasons.isNotEmpty()) {
            Log.w(TAG, "Response sanitized [conversationId=$conversationId]: " +
                    "reasons=${sanitizationReasons.joinToString()}, " +
                    "originalAction=${response.nextAction}, " +
                    "sanitizedAction=$sanitizedAction")
        }

        return SanitizedResponse(
            assistantMessage = errorMessage ?: assistantMessage,
            nextAction = sanitizedAction,
            question = response.question,
            extractedData = response.extractedData,
            confirmationCard = if (sanitizedAction == NextAction.CONFIRM) response.confirmationCard else null,
            placeSearchParams = if (sanitizedAction == NextAction.FIND_PLACE) response.placeSearchParams else null,
            isComplete = sanitizedAction == NextAction.COMPLETE,
            wasSanitized = sanitizationReasons.isNotEmpty(),
            sanitizationReasons = sanitizationReasons
        )
    }

    /**
     * Sanitized response for UI rendering.
     */
    private data class SanitizedResponse(
        val assistantMessage: String,
        val nextAction: NextAction,
        val question: com.calleroo.app.domain.model.Question?,
        val extractedData: JsonObject?,
        val confirmationCard: com.calleroo.app.domain.model.ConfirmationCard?,
        val placeSearchParams: com.calleroo.app.domain.model.PlaceSearchParams?,
        val isComplete: Boolean,
        val wasSanitized: Boolean = false,
        val sanitizationReasons: List<String> = emptyList()
    )
}