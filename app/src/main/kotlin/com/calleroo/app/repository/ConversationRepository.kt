package com.calleroo.app.repository

import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.ChatMessage
import com.calleroo.app.domain.model.ClientAction
import com.calleroo.app.domain.model.ConversationRequest
import com.calleroo.app.domain.model.ConversationResponse
import com.calleroo.app.network.ConversationApi
import kotlinx.serialization.json.JsonObject
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ConversationRepository @Inject constructor(
    private val conversationApi: ConversationApi
) {
    /**
     * Sends the next turn to the backend.
     * The backend is the SOLE authority for conversation flow.
     * This method does NO local logic - it just passes data through.
     *
     * @param clientAction Optional deterministic action (CONFIRM/REJECT) that bypasses OpenAI
     * @param idempotencyKey Optional key to prevent duplicate actions (e.g., double-tap confirm)
     */
    suspend fun nextTurn(
        conversationId: String,
        agentType: AgentType,
        userMessage: String,
        slots: JsonObject,
        messageHistory: List<ChatMessage>,
        debug: Boolean = false,
        clientAction: ClientAction? = null,
        idempotencyKey: String? = null
    ): Result<ConversationResponse> {
        return try {
            val request = ConversationRequest(
                conversationId = conversationId,
                agentType = agentType,
                userMessage = userMessage,
                slots = slots,
                messageHistory = messageHistory,
                debug = debug,
                clientAction = clientAction,
                idempotencyKey = idempotencyKey
            )
            val response = conversationApi.nextTurn(request)
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
