package com.calleroo.app.ui.viewmodel

import androidx.lifecycle.ViewModel
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.ResolvedPlace
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import javax.inject.Inject

/**
 * ViewModel scoped to the task flow navigation graph.
 *
 * This ViewModel holds state that needs to be shared across Screens 2, 3, and 4:
 * - Screen 2 (Chat): Sets conversationId, agentType, updates slots
 * - Screen 3 (PlaceSearch): Reads slots, sets resolvedPlace
 * - Screen 4 (CallSummary): Reads slots and resolvedPlace for /call/brief request
 *
 * This approach avoids passing complex data through URL parameters.
 */
@HiltViewModel
class TaskSessionViewModel @Inject constructor() : ViewModel() {

    // Set once when entering chat screen
    var conversationId: String = ""
        private set

    var agentType: AgentType = AgentType.STOCK_CHECKER
        private set

    // Updated by Chat screen on each /conversation/next response
    private val _slots = MutableStateFlow<JsonObject>(buildJsonObject {})
    val slots: StateFlow<JsonObject> = _slots.asStateFlow()

    // Set by PlaceSearch when user resolves a place
    private val _resolvedPlace = MutableStateFlow<ResolvedPlace?>(null)
    val resolvedPlace: StateFlow<ResolvedPlace?> = _resolvedPlace.asStateFlow()

    /**
     * Initialize the task session with conversation parameters.
     * Called by Chat screen when it starts.
     */
    fun initSession(conversationId: String, agentType: AgentType) {
        this.conversationId = conversationId
        this.agentType = agentType
        _slots.value = buildJsonObject {}
        _resolvedPlace.value = null
    }

    /**
     * Update slots with new data from Chat screen.
     * Called after each /conversation/next response merges extractedData.
     */
    fun updateSlots(newSlots: JsonObject) {
        _slots.value = newSlots
    }

    /**
     * Set the resolved place from PlaceSearch screen.
     */
    fun setResolvedPlace(place: ResolvedPlace) {
        _resolvedPlace.value = place
    }

    /**
     * Clear resolved place (e.g., when user navigates back from CallSummary to PlaceSearch).
     */
    fun clearResolvedPlace() {
        _resolvedPlace.value = null
    }
}
