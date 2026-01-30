package com.calleroo.app.ui.screens.callsummary

import com.calleroo.app.domain.model.CallBriefDisclosure
import com.calleroo.app.domain.model.CallBriefFallbacks
import com.calleroo.app.domain.model.ResolvedPlace

/**
 * State machine for Call Summary screen (Screen 4).
 *
 * State transitions:
 * - LoadingBrief (initial)
 * - LoadingBrief -> ReadyToReview (call brief loaded)
 * - LoadingBrief -> Error (API failure)
 * - ReadyToReview -> LoadingBrief (toggle changes trigger refresh)
 * - ReadyToReview -> EditingNumber (user edits phone)
 * - ReadyToReview -> StartingCall (user taps Start Call)
 * - EditingNumber -> ReadyToReview (number validated, refresh brief)
 * - StartingCall -> ReadyToReview (stub returns NOT_IMPLEMENTED)
 * - Error -> LoadingBrief (retry)
 */
sealed class CallSummaryState {

    /**
     * Loading state while fetching call brief from backend.
     */
    data object LoadingBrief : CallSummaryState()

    /**
     * Ready state with call brief loaded.
     * User can review and modify settings before starting call.
     */
    data class ReadyToReview(
        val place: ResolvedPlace,
        val objective: String,
        val scriptPreview: String,
        val checklist: List<ChecklistItem>,
        val disclosure: CallBriefDisclosure,
        val fallbacks: CallBriefFallbacks,
        val normalizedPhoneE164: String,
        val requiredFieldsMissing: List<String>
    ) : CallSummaryState() {

        /**
         * Check if Start Call button should be enabled.
         * Requires: all checklist items checked AND no missing required fields.
         */
        val canStartCall: Boolean
            get() = checklist.all { it.checked } && requiredFieldsMissing.isEmpty()

        /**
         * Check if there are missing required fields.
         */
        val hasBlocker: Boolean
            get() = requiredFieldsMissing.isNotEmpty()
    }

    /**
     * Editing phone number state.
     */
    data class EditingNumber(
        val currentInput: String,
        val error: String? = null,
        val previewE164: String? = null
    ) : CallSummaryState()

    /**
     * Starting call state (loading).
     */
    data object StartingCall : CallSummaryState()

    /**
     * Error state with message.
     */
    data class Error(val message: String) : CallSummaryState()
}

/**
 * A checklist item from the call brief.
 */
data class ChecklistItem(
    val text: String,
    val checked: Boolean
)
