package com.calleroo.app.ui.screens.callsummary

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.calleroo.app.BuildConfig
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.CallBriefDisclosure
import com.calleroo.app.domain.model.CallBriefFallbacks
import com.calleroo.app.domain.model.CallBriefPlace
import com.calleroo.app.domain.model.CreateScheduledTaskRequest
import com.calleroo.app.domain.model.DirectTaskPayload
import com.calleroo.app.domain.model.ResolvedPlace
import com.calleroo.app.repository.CallBriefRepository
import com.calleroo.app.repository.SchedulerRepository
import com.calleroo.app.ui.viewmodel.TaskSessionViewModel
import com.google.i18n.phonenumbers.PhoneNumberUtil
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import javax.inject.Inject

@HiltViewModel
class CallSummaryViewModel @Inject constructor(
    private val callBriefRepository: CallBriefRepository,
    private val schedulerRepository: SchedulerRepository
) : ViewModel() {

    private val _state = MutableStateFlow<CallSummaryState>(CallSummaryState.LoadingBrief)
    val state: StateFlow<CallSummaryState> = _state.asStateFlow()

    private val phoneNumberUtil = PhoneNumberUtil.getInstance()

    // Current settings (preserved across state changes)
    private var currentDisclosure = CallBriefDisclosure()
    private var currentFallbacks = CallBriefFallbacks()
    private var currentPhone: String = ""
    private var currentPlace: ResolvedPlace? = null

    // Debounce job for toggle changes
    private var debounceJob: Job? = null

    // TaskSession reference (set on init)
    private var conversationId: String = ""
    private var agentType: AgentType = AgentType.STOCK_CHECKER
    private var slots: JsonObject = JsonObject(emptyMap())

    // Script preview for V3 call start
    private var currentScriptPreview: String = ""

    // Schedule date/time (preserved across state changes)
    private var scheduleDate: LocalDate? = null
    private var scheduleTime: LocalTime? = null

    // Navigation callback for call status screen
    private val _navigateToCallStatus = MutableStateFlow<String?>(null)
    val navigateToCallStatus: StateFlow<String?> = _navigateToCallStatus.asStateFlow()

    // Navigation callback for scheduled confirmation screen (agentType, scheduledTimeUtc)
    private val _navigateToScheduledConfirmation = MutableStateFlow<Pair<String, String>?>(null)
    val navigateToScheduledConfirmation: StateFlow<Pair<String, String>?> = _navigateToScheduledConfirmation.asStateFlow()

    // Snackbar messages for errors
    private val _snackbarMessage = MutableSharedFlow<String>()
    val snackbarMessage: SharedFlow<String> = _snackbarMessage.asSharedFlow()

    /**
     * Clear navigation event after consumption.
     */
    fun clearNavigateToCallStatus() {
        _navigateToCallStatus.value = null
    }

    /**
     * Clear scheduled confirmation navigation event after consumption.
     */
    fun clearNavigateToScheduledConfirmation() {
        _navigateToScheduledConfirmation.value = null
    }

    companion object {
        private const val TAG = "CallSummaryViewModel"
        private const val DEBOUNCE_MS = 300L
    }

    /**
     * Initialize with task session data.
     * Called when screen is first displayed.
     */
    fun initialize(taskSession: TaskSessionViewModel) {
        val resolvedPlace = taskSession.resolvedPlace.value
        if (resolvedPlace == null) {
            _state.value = CallSummaryState.Error("No place selected")
            return
        }

        this.conversationId = taskSession.conversationId
        this.agentType = taskSession.agentType
        this.slots = taskSession.slots.value
        this.currentPlace = resolvedPlace
        this.currentPhone = resolvedPlace.phoneE164

        loadCallBrief()
    }

    /**
     * Load call brief from backend.
     */
    private fun loadCallBrief() {
        val place = currentPlace ?: run {
            _state.value = CallSummaryState.Error("No place selected")
            return
        }

        _state.value = CallSummaryState.LoadingBrief

        viewModelScope.launch {
            val briefPlace = CallBriefPlace(
                placeId = place.placeId,
                businessName = place.businessName,
                formattedAddress = place.formattedAddress,
                phoneE164 = currentPhone
            )

            val result = callBriefRepository.getCallBrief(
                conversationId = conversationId,
                agentType = agentType.name,
                place = briefPlace,
                slots = slots,
                disclosure = currentDisclosure,
                fallbacks = currentFallbacks,
                debug = true
            )

            result.fold(
                onSuccess = { response ->
                    Log.d(TAG, "Call brief loaded: objective='${response.objective}', missing=${response.requiredFieldsMissing}")

                    // Store script preview for V3 call start
                    currentScriptPreview = response.scriptPreview

                    _state.value = CallSummaryState.ReadyToReview(
                        place = place,
                        objective = response.objective,
                        scriptPreview = response.scriptPreview,
                        checklist = response.confirmationChecklist.map { ChecklistItem(it, false) },
                        disclosure = currentDisclosure,
                        fallbacks = currentFallbacks,
                        normalizedPhoneE164 = response.normalizedPhoneE164,
                        requiredFieldsMissing = response.requiredFieldsMissing,
                        scheduleDate = scheduleDate,
                        scheduleTime = scheduleTime,
                        isSchedulerAvailable = schedulerRepository.isAvailable
                    )
                },
                onFailure = { error ->
                    Log.e(TAG, "Failed to load call brief", error)
                    _state.value = CallSummaryState.Error(
                        error.message ?: "Failed to load call brief"
                    )
                }
            )
        }
    }

    /**
     * Toggle a checklist item.
     */
    fun toggleChecklistItem(index: Int) {
        val currentState = _state.value
        if (currentState !is CallSummaryState.ReadyToReview) return

        val newChecklist = currentState.checklist.mapIndexed { i, item ->
            if (i == index) item.copy(checked = !item.checked) else item
        }

        _state.value = currentState.copy(checklist = newChecklist)
    }

    /**
     * Update disclosure setting with debounced refresh.
     */
    fun updateDisclosure(nameShare: Boolean? = null, phoneShare: Boolean? = null) {
        currentDisclosure = currentDisclosure.copy(
            nameShare = nameShare ?: currentDisclosure.nameShare,
            phoneShare = phoneShare ?: currentDisclosure.phoneShare
        )

        val currentState = _state.value
        if (currentState is CallSummaryState.ReadyToReview) {
            _state.value = currentState.copy(disclosure = currentDisclosure)
        }

        debouncedRefresh()
    }

    /**
     * Update fallback setting with debounced refresh.
     */
    fun updateFallbacks(
        askETA: Boolean? = null,
        askNearestStore: Boolean? = null,
        retryIfNoAnswer: Boolean? = null,
        retryIfBusy: Boolean? = null,
        leaveVoicemail: Boolean? = null
    ) {
        currentFallbacks = currentFallbacks.copy(
            askETA = askETA ?: currentFallbacks.askETA,
            askNearestStore = askNearestStore ?: currentFallbacks.askNearestStore,
            retryIfNoAnswer = retryIfNoAnswer ?: currentFallbacks.retryIfNoAnswer,
            retryIfBusy = retryIfBusy ?: currentFallbacks.retryIfBusy,
            leaveVoicemail = leaveVoicemail ?: currentFallbacks.leaveVoicemail
        )

        val currentState = _state.value
        if (currentState is CallSummaryState.ReadyToReview) {
            _state.value = currentState.copy(fallbacks = currentFallbacks)
        }

        debouncedRefresh()
    }

    /**
     * Enter phone editing mode.
     */
    fun startEditingNumber() {
        _state.value = CallSummaryState.EditingNumber(
            currentInput = currentPhone,
            error = null,
            previewE164 = currentPhone
        )
    }

    /**
     * Update phone number input during editing.
     */
    fun updatePhoneInput(input: String) {
        val currentState = _state.value
        if (currentState !is CallSummaryState.EditingNumber) return

        // Try to parse and format as E.164
        val previewE164 = try {
            val parsed = phoneNumberUtil.parse(input, "AU")
            if (phoneNumberUtil.isValidNumber(parsed)) {
                phoneNumberUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
            } else {
                null
            }
        } catch (e: Exception) {
            null
        }

        _state.value = currentState.copy(
            currentInput = input,
            error = null,
            previewE164 = previewE164
        )
    }

    /**
     * Confirm phone number edit.
     */
    fun confirmPhoneEdit() {
        val currentState = _state.value
        if (currentState !is CallSummaryState.EditingNumber) return

        // Validate and format
        val formattedE164 = try {
            val parsed = phoneNumberUtil.parse(currentState.currentInput, "AU")
            if (!phoneNumberUtil.isValidNumber(parsed)) {
                _state.value = currentState.copy(error = "Invalid phone number")
                return
            }
            phoneNumberUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
        } catch (e: Exception) {
            _state.value = currentState.copy(error = "Invalid phone number format")
            return
        }

        currentPhone = formattedE164
        loadCallBrief()
    }

    /**
     * Cancel phone number edit.
     */
    fun cancelPhoneEdit() {
        loadCallBrief()
    }

    /**
     * Start a real Twilio call (Step 4 - V3 API).
     *
     * This initiates an actual outbound call via Twilio.
     * On success, navigates to CallStatus screen.
     */
    fun startCall() {
        val currentState = _state.value
        if (currentState !is CallSummaryState.ReadyToReview) return
        if (!currentState.canStartCall) return

        _state.value = CallSummaryState.StartingCall

        viewModelScope.launch {
            val result = callBriefRepository.startCallV3(
                conversationId = conversationId,
                agentType = agentType.name,
                placeId = currentPlace?.placeId ?: "manual",
                phoneE164 = currentPhone,
                slots = slots,
                scriptPreview = currentScriptPreview
            )

            result.fold(
                onSuccess = { response ->
                    Log.i(TAG, "Call started: callId=${response.callId}, status=${response.status}")

                    // Navigate to CallStatus screen with the call ID
                    _navigateToCallStatus.value = response.callId
                },
                onFailure = { error ->
                    Log.e(TAG, "Failed to start call", error)
                    _state.value = CallSummaryState.Error(
                        error.message ?: "Failed to start call"
                    )
                }
            )
        }
    }

    /**
     * Retry after error.
     */
    fun retry() {
        loadCallBrief()
    }

    /**
     * Debounced refresh for toggle changes.
     */
    private fun debouncedRefresh() {
        debounceJob?.cancel()
        debounceJob = viewModelScope.launch {
            delay(DEBOUNCE_MS)
            loadCallBrief()
        }
    }

    /**
     * Update selected schedule date.
     */
    fun updateScheduleDate(date: LocalDate?) {
        scheduleDate = date
        val currentState = _state.value
        if (currentState is CallSummaryState.ReadyToReview) {
            _state.value = currentState.copy(scheduleDate = date)
        }
    }

    /**
     * Update selected schedule time.
     */
    fun updateScheduleTime(time: LocalTime?) {
        scheduleTime = time
        val currentState = _state.value
        if (currentState is CallSummaryState.ReadyToReview) {
            _state.value = currentState.copy(scheduleTime = time)
        }
    }

    /**
     * Schedule a call for the selected date and time.
     * On success, navigates to ScheduledConfirmationScreen.
     */
    fun scheduleCall() {
        val currentState = _state.value
        if (currentState !is CallSummaryState.ReadyToReview) return
        if (!currentState.canScheduleCall) return

        val date = scheduleDate ?: return
        val time = scheduleTime ?: return
        val place = currentPlace ?: return

        // Combine date and time in local timezone
        val localZone = ZoneId.systemDefault()
        val localDateTime = ZonedDateTime.of(date, time, localZone)

        // Check if scheduled time is in the past (must be at least 1 minute in future)
        val now = ZonedDateTime.now(localZone)
        if (localDateTime.isBefore(now.plusMinutes(1))) {
            viewModelScope.launch {
                _snackbarMessage.emit("Please select a time at least 1 minute in the future")
            }
            return
        }

        _state.value = CallSummaryState.SchedulingCall

        viewModelScope.launch {
            // Convert to UTC ISO 8601
            val utcDateTime = localDateTime.withZoneSameInstant(ZoneOffset.UTC)
            val runAtUtc = utcDateTime.format(DateTimeFormatter.ISO_INSTANT)

            Log.i(TAG, "Scheduling call for: $runAtUtc (local: $localDateTime)")

            // Ensure backend URL has trailing slash
            val backendUrl = BuildConfig.BACKEND_BASE_URL.let { url ->
                if (url.endsWith("/")) url else "$url/"
            }

            val request = CreateScheduledTaskRequest(
                runAtUtc = runAtUtc,
                backendBaseUrl = backendUrl,
                agentType = agentType.name,
                conversationId = conversationId,
                mode = "DIRECT",
                payload = DirectTaskPayload(
                    placeId = place.placeId,
                    phoneE164 = currentPhone,
                    scriptPreview = currentScriptPreview,
                    slots = slots
                ),
                timezone = localZone.id
            )

            val result = schedulerRepository.createTask(request)

            result.fold(
                onSuccess = { response ->
                    Log.i(TAG, "Call scheduled: taskId=${response.taskId}, status=${response.status}")

                    // Navigate to ScheduledConfirmation screen
                    _navigateToScheduledConfirmation.value = Pair(agentType.name, runAtUtc)
                },
                onFailure = { error ->
                    Log.e(TAG, "Failed to schedule call", error)

                    // Show error in snackbar, stay on screen for retry
                    viewModelScope.launch {
                        _snackbarMessage.emit(error.message ?: "Failed to schedule call")
                    }

                    // Return to ReadyToReview state
                    loadCallBrief()
                }
            )
        }
    }
}
