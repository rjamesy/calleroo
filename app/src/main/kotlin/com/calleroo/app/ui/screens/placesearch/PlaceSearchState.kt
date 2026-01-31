package com.calleroo.app.ui.screens.placesearch

import com.calleroo.app.domain.model.PlaceCandidate
import com.calleroo.app.domain.model.ResolvedPlace

/**
 * State machine for Place Search screen (Screen 3).
 *
 * State transitions:
 * - Loading (initial search)
 * - Loading -> Results (candidates found)
 * - Loading -> NoResults (no candidates at current radius)
 * - Loading -> Error (API failure)
 * - Results -> Loading (expand radius)
 * - Results -> Resolving (user confirms selection)
 * - NoResults -> Loading (expand radius)
 * - Resolving -> Resolved (place details confirmed with valid phone)
 * - Resolving -> Error (place has no valid phone)
 * - Error -> Results (go back to results)
 */
sealed class PlaceSearchState {

    /**
     * Loading state while searching for places.
     */
    data class Loading(
        val passNumber: Int = 1,
        val radiusKm: Int = 25,
        val message: String = "Searching..."
    ) : PlaceSearchState()

    /**
     * Results state with place candidates.
     */
    data class Results(
        val passNumber: Int,
        val radiusKm: Int,
        val candidates: List<PlaceCandidate>,
        val selectedPlaceId: String? = null,
        val canExpand: Boolean,
        val message: String? = null
    ) : PlaceSearchState() {
        val selectedCandidate: PlaceCandidate?
            get() = selectedPlaceId?.let { id -> candidates.find { it.placeId == id } }

        val hasSelection: Boolean
            get() = selectedPlaceId != null
    }

    /**
     * No results found at current radius.
     */
    data class NoResults(
        val passNumber: Int,
        val radiusKm: Int,
        val canExpand: Boolean,
        val error: String? = null
    ) : PlaceSearchState()

    /**
     * Error state with context for retry/manual entry.
     */
    data class Error(
        val message: String,
        val query: String = "",
        val area: String = "",
        val passNumber: Int = 1,
        val radiusKm: Int = 25
    ) : PlaceSearchState()

    /**
     * Resolving state while fetching place details.
     */
    data class Resolving(
        val placeId: String,
        val placeName: String
    ) : PlaceSearchState()

    /**
     * Final resolved state with selected place.
     * Contains all data needed for the next screen.
     */
    data class Resolved(
        val businessName: String,
        val formattedAddress: String?,
        val phoneE164: String,
        val placeId: String
    ) : PlaceSearchState() {
        fun toResolvedPlace(): ResolvedPlace = ResolvedPlace(
            placeId = placeId,
            businessName = businessName,
            formattedAddress = formattedAddress,
            phoneE164 = phoneE164
        )
    }
}
