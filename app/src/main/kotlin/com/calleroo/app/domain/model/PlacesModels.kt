package com.calleroo.app.domain.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Request to search for places.
 * Used with POST /places/search endpoint.
 */
@Serializable
data class PlaceSearchRequest(
    val query: String,
    val area: String,
    val country: String = "AU",
    @SerialName("radius_km")
    val radiusKm: Int = 25
)

/**
 * A place candidate from Google Places API.
 */
@Serializable
data class PlaceCandidate(
    val placeId: String,
    val name: String,
    val formattedAddress: String? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    val distanceMeters: Int? = null,
    val hasValidPhone: Boolean = false
)

/**
 * Response from place search.
 */
@Serializable
data class PlaceSearchResponse(
    val passNumber: Int = 1,  // 1=25km, 2=50km, 3=100km
    val radiusKm: Int,
    val candidates: List<PlaceCandidate>,
    val error: String? = null
) {
    val hasError: Boolean get() = error != null
    val isEmpty: Boolean get() = candidates.isEmpty()
    val canExpand: Boolean get() = radiusKm < 100
    val nextRadiusKm: Int? get() = when (radiusKm) {
        25 -> 50
        50 -> 100
        else -> null
    }
}

/**
 * Request for place details.
 * Used with POST /places/details endpoint.
 */
@Serializable
data class PlaceDetailsRequest(
    val placeId: String,
    val country: String = "AU"
)

/**
 * Response from place details.
 * phoneE164 is the E.164 formatted phone number, or null if no valid phone.
 */
@Serializable
data class PlaceDetailsResponse(
    val placeId: String,
    val name: String,
    val formattedAddress: String? = null,
    val phoneE164: String? = null,
    val error: String? = null
) {
    val hasValidPhone: Boolean get() = phoneE164 != null && error == null
    val hasError: Boolean get() = error != null
}

/**
 * Represents a resolved place selection with all required data.
 * Used to pass data to the next screen after place selection.
 */
data class ResolvedPlace(
    val placeId: String,
    val businessName: String,
    val formattedAddress: String?,
    val phoneE164: String
)
