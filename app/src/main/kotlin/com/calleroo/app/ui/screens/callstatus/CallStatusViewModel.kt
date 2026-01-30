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

    private val _state = MutableStateFlow<CallStatusState>(
        CallStatusState.Polling(callId = callId)
    )
    val state: StateFlow<CallStatusState> = _state.asStateFlow()

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

                        // Update state based on response
                        when {
                            response.status == "completed" -> {
                                _state.value = CallStatusState.Completed(
                                    callId = response.callId,
                                    durationSeconds = response.durationSeconds ?: 0,
                                    transcript = response.transcript,
                                    outcome = CallOutcome.fromJson(response.outcome)
                                )
                                return@launch  // Stop polling
                            }
                            response.isTerminal -> {
                                _state.value = CallStatusState.Failed(
                                    callId = response.callId,
                                    status = response.status,
                                    error = response.error
                                )
                                return@launch  // Stop polling
                            }
                            else -> {
                                // Update polling state
                                _state.value = CallStatusState.Polling(
                                    callId = response.callId,
                                    status = response.status,
                                    pollCount = pollCount
                                )
                            }
                        }
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

            // Timeout - exceeded max polls
            Log.w(TAG, "Polling timeout exceeded for call $callId")
            _state.value = CallStatusState.Failed(
                callId = callId,
                status = "timeout",
                error = "Call status check timed out"
            )
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
