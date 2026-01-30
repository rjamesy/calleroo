package com.calleroo.app.repository

import com.calleroo.app.domain.model.CallBriefDisclosure
import com.calleroo.app.domain.model.CallBriefFallbacks
import com.calleroo.app.domain.model.CallBriefPlace
import com.calleroo.app.domain.model.CallBriefRequestV2
import com.calleroo.app.domain.model.CallBriefResponseV2
import com.calleroo.app.domain.model.CallStartRequestV2
import com.calleroo.app.domain.model.CallStartResponseV2
import com.calleroo.app.domain.model.CallStartRequestV3
import com.calleroo.app.domain.model.CallStartResponseV3
import com.calleroo.app.domain.model.CallStatusResponseV1
import com.calleroo.app.network.ConversationApi
import kotlinx.serialization.json.JsonObject
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for Call Brief operations.
 *
 * This repository handles:
 * - /call/brief: Always calls OpenAI to generate call script preview
 * - /call/start/v2: Stub in Step 3 (returns NOT_IMPLEMENTED)
 */
@Singleton
class CallBriefRepository @Inject constructor(
    private val conversationApi: ConversationApi
) {
    /**
     * Generate a call brief with script preview.
     *
     * This endpoint ALWAYS calls OpenAI to generate:
     * - objective: Short description of call purpose
     * - scriptPreview: Plain text call script preview
     * - confirmationChecklist: Items user should verify
     *
     * @param conversationId Current conversation ID
     * @param agentType Agent type (STOCK_CHECKER or RESTAURANT_RESERVATION)
     * @param place Place information (name, address, phone)
     * @param slots Collected conversation slots
     * @param disclosure User disclosure settings
     * @param fallbacks Fallback behaviors
     */
    suspend fun getCallBrief(
        conversationId: String,
        agentType: String,
        place: CallBriefPlace,
        slots: JsonObject,
        disclosure: CallBriefDisclosure = CallBriefDisclosure(),
        fallbacks: CallBriefFallbacks = CallBriefFallbacks(),
        debug: Boolean = false
    ): Result<CallBriefResponseV2> {
        return try {
            val request = CallBriefRequestV2(
                conversationId = conversationId,
                agentType = agentType,
                place = place,
                slots = slots,
                disclosure = disclosure,
                fallbacks = fallbacks,
                debug = debug
            )
            val response = conversationApi.callBrief(request)
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Start a call (stub in Step 3).
     *
     * This endpoint validates the phone number but does NOT actually initiate a call.
     * Returns NOT_IMPLEMENTED in Step 3.
     *
     * @param conversationId Current conversation ID
     * @param agentType Agent type
     * @param placeId Place ID (or "manual" for manual entry)
     * @param phoneE164 Phone number in E.164 format
     * @param slots Collected conversation slots
     */
    suspend fun startCall(
        conversationId: String,
        agentType: String,
        placeId: String,
        phoneE164: String,
        slots: JsonObject
    ): Result<CallStartResponseV2> {
        return try {
            val request = CallStartRequestV2(
                conversationId = conversationId,
                agentType = agentType,
                placeId = placeId,
                phoneE164 = phoneE164,
                slots = slots
            )
            val response = conversationApi.callStart(request)
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ============================================================
    // Step 4: Real Twilio Calls
    // ============================================================

    /**
     * Start a real Twilio call.
     *
     * This endpoint initiates an actual outbound call via Twilio.
     *
     * @param conversationId Current conversation ID
     * @param agentType Agent type
     * @param placeId Place ID (or "manual" for manual entry)
     * @param phoneE164 Phone number in E.164 format
     * @param slots Collected conversation slots
     * @param scriptPreview The script that will be spoken during the call
     */
    suspend fun startCallV3(
        conversationId: String,
        agentType: String,
        placeId: String,
        phoneE164: String,
        slots: JsonObject,
        scriptPreview: String
    ): Result<CallStartResponseV3> {
        return try {
            val request = CallStartRequestV3(
                conversationId = conversationId,
                agentType = agentType,
                placeId = placeId,
                phoneE164 = phoneE164,
                slots = slots,
                scriptPreview = scriptPreview
            )
            val response = conversationApi.callStartV3(request)
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get the status of a Twilio call.
     *
     * @param callId The Twilio Call SID
     * @return Call status with transcript and outcome when available
     */
    suspend fun getCallStatus(callId: String): Result<CallStatusResponseV1> {
        return try {
            val response = conversationApi.getCallStatus(callId)
            Result.success(response)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
