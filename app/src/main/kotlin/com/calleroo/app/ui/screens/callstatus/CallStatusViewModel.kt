package com.calleroo.app.ui.screens.callstatus

import android.util.Log
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.calleroo.app.repository.CallBriefRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class CallStatusViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val repository: CallBriefRepository
) : ViewModel() {

    private val callId: String = checkNotNull(savedStateHandle["callId"]) {
        "callId is required"
    }

    private val agentType: String = checkNotNull(savedStateHandle["agentType"]) {
        "agentType is required"
    }

    private val _state = MutableStateFlow<CallStatusState>(
        CallStatusState.Polling(callId = callId)
    )
    val state: StateFlow<CallStatusState> = _state.asStateFlow()

    // Navigation signal for when call reaches terminal status
    private val _navigateToResults = MutableStateFlow<Pair<String, String>?>(null)
    val navigateToResults: StateFlow<Pair<String, String>?> = _navigateToResults.asStateFlow()

    private var pollingJob: Job? = null

    companion object {
        private const val TAG = "CallStatusViewModel"
        private const val POLL_INTERVAL_MS = 2000L  // 2 seconds
        private const val MAX_POLL_COUNT = 150       // 5 minutes max (150 * 2s = 300s)
    }

    init {
        startPolling()
    }

    /**
     * Called after navigation to results has occurred.
     */
    fun onNavigatedToResults() {
        _navigateToResults.value = null
    }

    /**
     * Start polling for call status updates.
     */
    private fun startPolling() {
        pollingJob?.cancel()
        pollingJob = viewModelScope.launch {
            var pollCount = 0

            while (isActive && pollCount < MAX_POLL_COUNT) {
                pollCount++
                Log.d(TAG, "Polling call status: callId=$callId, poll=$pollCount")

                val result = repository.getCallStatus(callId)

                result.fold(
                    onSuccess = { response ->
                        Log.d(TAG, "Call status: ${response.status}, duration=${response.durationSeconds}")

                        // Check if call reached terminal status
                        if (response.isTerminal) {
                            Log.d(TAG, "Call reached terminal status: ${response.status}")
                            // Signal navigation to CallResults screen
                            _navigateToResults.value = Pair(callId, agentType)
                            return@launch  // Stop polling
                        }

                        // Still in progress - update polling state
                        _state.value = CallStatusState.Polling(
                            callId = response.callId,
                            status = response.status,
                            pollCount = pollCount
                        )
                    },
                    onFailure = { error ->
                        Log.e(TAG, "Failed to get call status", error)
                        // Don't fail immediately on transient errors, keep polling
                        // But update poll count in state
                        val currentState = _state.value
                        if (currentState is CallStatusState.Polling) {
                            _state.value = currentState.copy(pollCount = pollCount)
                        }
                    }
                )

                // Wait before next poll
                delay(POLL_INTERVAL_MS)
            }

            // Timeout - exceeded max polls, navigate to results anyway
            Log.w(TAG, "Polling timeout exceeded for call $callId")
            _navigateToResults.value = Pair(callId, agentType)
        }
    }

    /**
     * Retry polling (used after failure).
     */
    fun retry() {
        _state.value = CallStatusState.Polling(callId = callId)
        startPolling()
    }

    override fun onCleared() {
        super.onCleared()
        pollingJob?.cancel()
    }
}
