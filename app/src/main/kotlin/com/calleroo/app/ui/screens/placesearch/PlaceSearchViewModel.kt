package com.calleroo.app.ui.screens.placesearch

import android.util.Log
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.calleroo.app.BuildConfig
import com.calleroo.app.domain.model.PlaceCandidate
import com.calleroo.app.repository.PlacesRepository
import com.google.i18n.phonenumbers.NumberParseException
import com.google.i18n.phonenumbers.PhoneNumberUtil
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import javax.inject.Inject

/**
 * ViewModel for Place Search screen (Screen 3).
 *
 * Manages the state machine for place search:
 * - Initial search with 25km radius
 * - Radius expansion (25 -> 50 -> 100km) on user request ONLY
 * - Place selection and detail fetching
 * - Phone number validation (E.164 required)
 * - Manual entry fallback with libphonenumber validation
 *
 * NO local "smart" logic - all data comes from backend.
 * NO GPS/location - uses area string from chat.
 * NO auto-expansion - user must explicitly tap expand.
 */
@HiltViewModel
class PlaceSearchViewModel @Inject constructor(
    private val placesRepository: PlacesRepository,
    savedStateHandle: SavedStateHandle
) : ViewModel() {

    private val _state = MutableStateFlow<PlaceSearchState>(PlaceSearchState.Loading())
    val state: StateFlow<PlaceSearchState> = _state.asStateFlow()

    // Manual entry dialog state
    private val _showManualEntryDialog = MutableStateFlow(false)
    val showManualEntryDialog: StateFlow<Boolean> = _showManualEntryDialog.asStateFlow()

    private val _manualEntryError = MutableStateFlow<String?>(null)
    val manualEntryError: StateFlow<String?> = _manualEntryError.asStateFlow()

    // Navigation arguments (URL decoded)
    val query: String = URLDecoder.decode(
        savedStateHandle.get<String>("query") ?: "",
        StandardCharsets.UTF_8.toString()
    )
    val area: String = URLDecoder.decode(
        savedStateHandle.get<String>("area") ?: "",
        StandardCharsets.UTF_8.toString()
    )

    // Track current state for retry and expansion
    private var currentRadiusKm: Int = INITIAL_RADIUS_KM
    private var currentPassNumber: Int = 1

    // Keep last results for returning from error state
    private var lastResults: PlaceSearchState.Results? = null

    // Phone number utility for manual entry validation
    private val phoneUtil = PhoneNumberUtil.getInstance()

    companion object {
        private const val TAG = "PlaceSearchViewModel"
        private const val INITIAL_RADIUS_KM = 25
        private const val EXPANDED_RADIUS_KM = 50
        private const val MAX_RADIUS_KM = 100
        private const val DEFAULT_REGION = "AU"
    }

    init {
        // Start search immediately
        if (query.isNotBlank() && area.isNotBlank()) {
            searchPlaces(INITIAL_RADIUS_KM)
        } else {
            Log.e(TAG, "Missing search parameters: query='$query', area='$area'")
            _state.value = PlaceSearchState.Error(
                message = "Missing search parameters",
                query = query,
                area = area,
                passNumber = 1,
                radiusKm = INITIAL_RADIUS_KM
            )
        }
    }

    /**
     * Search for places at the specified radius.
     */
    fun searchPlaces(radiusKm: Int = currentRadiusKm) {
        currentRadiusKm = radiusKm
        currentPassNumber = when (radiusKm) {
            25 -> 1
            50 -> 2
            100 -> 3
            else -> 1
        }

        _state.value = PlaceSearchState.Loading(
            passNumber = currentPassNumber,
            radiusKm = radiusKm,
            message = "Searching within ${radiusKm}km..."
        )

        viewModelScope.launch {
            Log.d(TAG, "Searching: query='$query', area='$area', radius=${radiusKm}km (pass $currentPassNumber)")

            val result = placesRepository.searchPlaces(
                query = query,
                area = area,
                radiusKm = radiusKm
            )

            result.fold(
                onSuccess = { response ->
                    Log.d(TAG, "Search success: ${response.candidates.size} candidates, pass=${response.passNumber}, error=${response.error}")

                    // Use passNumber from backend response
                    val passNumber = response.passNumber
                    currentPassNumber = passNumber

                    if (response.hasError && response.error == "AREA_NOT_FOUND") {
                        _state.value = PlaceSearchState.NoResults(
                            passNumber = passNumber,
                            radiusKm = response.radiusKm,
                            canExpand = false,
                            error = "Could not find location: $area"
                        )
                    } else if (response.isEmpty) {
                        _state.value = PlaceSearchState.NoResults(
                            passNumber = passNumber,
                            radiusKm = response.radiusKm,
                            canExpand = response.canExpand,
                            error = null
                        )
                    } else {
                        val resultsState = PlaceSearchState.Results(
                            passNumber = passNumber,
                            radiusKm = response.radiusKm,
                            candidates = response.candidates,
                            selectedPlaceId = null,
                            canExpand = response.canExpand,
                            message = null
                        )
                        lastResults = resultsState
                        _state.value = resultsState
                    }
                },
                onFailure = { error ->
                    Log.e(TAG, "Search failed", error)
                    _state.value = PlaceSearchState.Error(
                        message = error.message ?: "Search failed",
                        query = query,
                        area = area,
                        passNumber = currentPassNumber,
                        radiusKm = currentRadiusKm
                    )
                }
            )
        }
    }

    /**
     * Expand the search radius.
     * Only available when current radius < 100km.
     * MUST be user-triggered - no auto-expansion.
     */
    fun expandRadius() {
        val nextRadius = when (currentRadiusKm) {
            INITIAL_RADIUS_KM -> EXPANDED_RADIUS_KM
            EXPANDED_RADIUS_KM -> MAX_RADIUS_KM
            else -> return // Already at max
        }
        searchPlaces(nextRadius)
    }

    /**
     * Retry the current search with same parameters.
     */
    fun retry() {
        searchPlaces(currentRadiusKm)
    }

    /**
     * Select a place candidate (highlight in UI).
     */
    fun selectCandidate(candidate: PlaceCandidate) {
        val current = _state.value
        if (current is PlaceSearchState.Results) {
            _state.value = current.copy(selectedPlaceId = candidate.placeId)
        }
    }

    /**
     * Confirm the selected place and fetch details.
     * Validates that the place has a valid E.164 phone number.
     */
    fun confirmSelection() {
        val current = _state.value
        if (current !is PlaceSearchState.Results || current.selectedCandidate == null) {
            Log.w(TAG, "confirmSelection called without valid selection")
            return
        }

        val candidate = current.selectedCandidate!!
        _state.value = PlaceSearchState.Resolving(
            placeId = candidate.placeId,
            placeName = candidate.name
        )

        viewModelScope.launch {
            Log.d(TAG, "Fetching details for: ${candidate.name}")

            val result = placesRepository.getPlaceDetails(candidate.placeId)

            result.fold(
                onSuccess = { details ->
                    if (details.hasValidPhone && details.phoneE164 != null) {
                        Log.d(TAG, "Place resolved: ${details.name}, phone=${details.phoneE164}")

                        _state.value = PlaceSearchState.Resolved(
                            businessName = details.name,
                            formattedAddress = details.formattedAddress,
                            phoneE164 = details.phoneE164,
                            placeId = details.placeId
                        )
                    } else {
                        Log.w(TAG, "Place has no valid phone: ${details.name}, error=${details.error}")
                        _state.value = PlaceSearchState.Error(
                            message = "This place doesn't have a valid phone number. Pick another or enter manually.",
                            query = query,
                            area = area,
                            passNumber = currentPassNumber,
                            radiusKm = currentRadiusKm
                        )
                    }
                },
                onFailure = { error ->
                    Log.e(TAG, "Place details failed", error)
                    _state.value = PlaceSearchState.Error(
                        message = "Could not get place details: ${error.message}",
                        query = query,
                        area = area,
                        passNumber = currentPassNumber,
                        radiusKm = currentRadiusKm
                    )
                }
            )
        }
    }

    /**
     * Return to results from error state.
     */
    fun backToResults() {
        lastResults?.let {
            _state.value = it.copy(selectedPlaceId = null)
        }
    }

    // ========================================
    // Manual Entry Flow
    // ========================================

    /**
     * Open the manual entry dialog.
     */
    fun openManualEntry() {
        _manualEntryError.value = null
        _showManualEntryDialog.value = true
    }

    /**
     * Close the manual entry dialog.
     */
    fun closeManualEntry() {
        _showManualEntryDialog.value = false
        _manualEntryError.value = null
    }

    /**
     * Validate and submit a manually entered phone number.
     *
     * @param businessName The name of the business
     * @param phoneNumber The phone number entered by the user
     * @return true if valid and resolved, false if validation failed
     */
    fun submitManualEntry(businessName: String, phoneNumber: String): Boolean {
        // Validate business name
        if (businessName.isBlank()) {
            _manualEntryError.value = "Please enter a business name"
            return false
        }

        // Validate and normalize phone number using libphonenumber
        val normalizedPhone = normalizePhoneNumber(phoneNumber, DEFAULT_REGION)

        if (normalizedPhone == null) {
            _manualEntryError.value = "Invalid phone number. Please enter a valid Australian number."
            return false
        }

        Log.d(TAG, "Manual entry resolved: name='$businessName', phone='$normalizedPhone'")

        // Close dialog and set resolved state
        _showManualEntryDialog.value = false
        _manualEntryError.value = null

        _state.value = PlaceSearchState.Resolved(
            businessName = businessName.trim(),
            formattedAddress = null, // No address for manual entry
            phoneE164 = normalizedPhone,
            placeId = "manual" // Special marker for manual entries
        )

        return true
    }

    /**
     * Normalize a phone number to E.164 format using libphonenumber.
     *
     * @param phone Raw phone number string
     * @param defaultRegion Default region for parsing (e.g., "AU")
     * @return E.164 formatted phone or null if invalid
     */
    private fun normalizePhoneNumber(phone: String, defaultRegion: String): String? {
        if (phone.isBlank()) return null

        return try {
            val parsed = phoneUtil.parse(phone, defaultRegion)

            if (!phoneUtil.isValidNumber(parsed)) {
                Log.d(TAG, "Invalid phone number: $phone")
                return null
            }

            val e164 = phoneUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
            Log.d(TAG, "Normalized phone '$phone' to '$e164'")
            e164
        } catch (e: NumberParseException) {
            Log.d(TAG, "Could not parse phone '$phone': ${e.message}")
            null
        }
    }

    /**
     * Get the resolved place data.
     * Only valid when state is Resolved.
     *
     * DEBUG GUARD: Crashes in debug builds if called without valid phoneE164.
     */
    fun getResolvedPlace(): PlaceSearchState.Resolved? {
        val current = _state.value
        if (current is PlaceSearchState.Resolved) {
            // Debug guard: crash if phoneE164 is blank
            if (BuildConfig.ENABLE_LOCAL_LOGIC_GUARD && current.phoneE164.isBlank()) {
                throw RuntimeException("Place selection required before proceeding - phoneE164 is blank")
            }
            return current
        }
        return null
    }
}
