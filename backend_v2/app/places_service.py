"""
Google Places Service for Calleroo.
Handles geocoding, text search, and place details.

This service is DETERMINISTIC - NO OpenAI calls.
All place data comes directly from Google Places API.

Python 3.9 compatible - uses typing.Dict, typing.List, typing.Optional
"""

import logging
import math
import os
from typing import List, Optional, Tuple

import httpx
import phonenumbers
from phonenumbers import NumberParseException

from .models import PlaceCandidate, PlaceSearchResponse, PlaceDetailsResponse, GeocodeResponse

logger = logging.getLogger(__name__)


class GooglePlacesService:
    """Service for Google Places API operations."""

    GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

    # Allowed radius values in km
    ALLOWED_RADII = [25, 50, 100]

    # Pass number mapping: radius -> pass number
    RADIUS_TO_PASS = {25: 1, 50: 2, 100: 3}

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_PLACES_API_KEY")
        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is required for Places service")

        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Google Places service initialized")

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()
        logger.info("Google Places service closed")

    async def geocode_area(self, area: str, country: str) -> Optional[Tuple[float, float, str]]:
        """
        Geocode an area name to lat/lng coordinates.

        Args:
            area: Area name like "Browns Plains" or "Richmond VIC"
            country: Country code like "AU"

        Returns:
            Tuple of (latitude, longitude, formatted_address) or None if geocoding fails
        """
        params = {
            "address": f"{area} {country}",
            "key": self.api_key,
        }

        try:
            response = await self.http_client.get(self.GEOCODE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                location = result["geometry"]["location"]
                lat, lng = location["lat"], location["lng"]
                formatted_address = result.get("formatted_address", f"{area}, {country}")
                logger.debug(f"Geocoded '{area} {country}' to ({lat}, {lng})")
                return (lat, lng, formatted_address)

            logger.warning(f"Geocoding failed for '{area} {country}': {data.get('status')}")
            return None

        except Exception as e:
            logger.error(f"Geocoding error for '{area} {country}': {e}")
            return None

    async def geocode(self, area: str, country: str) -> GeocodeResponse:
        """
        Public geocode endpoint - geocode an area name.

        Args:
            area: Area name like "Browns Plains"
            country: Country code like "AU"

        Returns:
            GeocodeResponse with lat/lng or error
        """
        result = await self.geocode_area(area, country)
        if result is None:
            return GeocodeResponse(
                latitude=0.0,
                longitude=0.0,
                formattedAddress="",
                error=f"Could not geocode: {area}"
            )

        lat, lng, formatted_address = result
        return GeocodeResponse(
            latitude=lat,
            longitude=lng,
            formattedAddress=formatted_address,
            error=None
        )

    @staticmethod
    def _calculate_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
        """
        Calculate distance between two points using Haversine formula.

        Args:
            lat1, lng1: First point coordinates
            lat2, lng2: Second point coordinates

        Returns:
            Distance in meters
        """
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)

        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return int(R * c)

    async def text_search(
        self,
        query: str,
        area: str,
        country: str,
        radius_km: int
    ) -> PlaceSearchResponse:
        """
        Search for places using Google Places Text Search API.

        Uses area geocoding to bias results toward the specified location.
        NO GPS/device location is used - only the area string.

        Args:
            query: Search query (e.g., "JB Hi-Fi" or "Thai Palace restaurant")
            area: Area to search in (e.g., "Browns Plains" or "Richmond VIC")
            country: Country code (default "AU")
            radius_km: Search radius in kilometers (25, 50, or 100)

        Returns:
            PlaceSearchResponse with candidates or error
        """
        # Note: radius validation is now done in route handler (returns 400)
        # This is a fallback only
        if radius_km not in self.ALLOWED_RADII:
            logger.warning(f"Invalid radius {radius_km}km, coercing to 25km")
            radius_km = 25

        # Calculate pass number from radius
        pass_number = self.RADIUS_TO_PASS.get(radius_km, 1)

        # Geocode the area first to get coordinates for location bias
        coords = await self.geocode_area(area, country)
        if not coords:
            logger.warning(f"Could not geocode area '{area}', returning AREA_NOT_FOUND")
            return PlaceSearchResponse(
                passNumber=pass_number,
                radiusKm=radius_km,
                candidates=[],
                error="AREA_NOT_FOUND"
            )

        center_lat, center_lng, _ = coords
        radius_m = radius_km * 1000

        # Build the search query - include area in query string for better results
        search_query = f"{query} {area} {country}"

        params = {
            "query": search_query,
            "location": f"{center_lat},{center_lng}",
            "radius": radius_m,
            "key": self.api_key,
        }

        try:
            response = await self.http_client.get(self.TEXT_SEARCH_URL, params=params)
            response.raise_for_status()
            data = response.json()

            status = data.get("status")
            if status not in ["OK", "ZERO_RESULTS"]:
                logger.error(f"Places API error: {status}")
                return PlaceSearchResponse(
                    passNumber=pass_number,
                    radiusKm=radius_km,
                    candidates=[],
                    error="PLACES_ERROR"
                )

            # Parse results - max 10 candidates
            candidates: List[PlaceCandidate] = []
            for result in data.get("results", [])[:10]:
                place_id = result.get("place_id")
                name = result.get("name")

                # Skip results missing required fields
                if not place_id or not name:
                    continue

                location = result.get("geometry", {}).get("location", {})
                candidate_lat = location.get("lat")
                candidate_lng = location.get("lng")

                # Calculate distance from search center
                distance_meters = None
                if candidate_lat is not None and candidate_lng is not None:
                    distance_meters = self._calculate_distance_meters(
                        center_lat, center_lng,
                        candidate_lat, candidate_lng
                    )

                candidate = PlaceCandidate(
                    placeId=place_id,
                    name=name,
                    formattedAddress=result.get("formatted_address"),
                    lat=candidate_lat,
                    lng=candidate_lng,
                    distanceMeters=distance_meters,
                    hasValidPhone=False  # Unknown until details call
                )
                candidates.append(candidate)

            logger.info(f"Text search for '{query}' near '{area}': {len(candidates)} candidates (pass {pass_number})")
            return PlaceSearchResponse(
                passNumber=pass_number,
                radiusKm=radius_km,
                candidates=candidates,
                error=None
            )

        except Exception as e:
            logger.error(f"Text search error: {e}")
            return PlaceSearchResponse(
                passNumber=pass_number,
                radiusKm=radius_km,
                candidates=[],
                error="PLACES_ERROR"
            )

    async def place_details(self, place_id: str) -> PlaceDetailsResponse:
        """
        Get detailed information about a specific place.

        Fetches phone number and normalizes to E.164 format.

        Args:
            place_id: Google Place ID

        Returns:
            PlaceDetailsResponse with phone number or error
        """
        params = {
            "place_id": place_id,
            "fields": "place_id,name,formatted_address,international_phone_number,formatted_phone_number",
            "key": self.api_key,
        }

        try:
            response = await self.http_client.get(self.PLACE_DETAILS_URL, params=params)
            response.raise_for_status()
            data = response.json()

            status = data.get("status")
            if status != "OK" or not data.get("result"):
                logger.warning(f"Place details failed for {place_id}: {status}")
                return PlaceDetailsResponse(
                    placeId=place_id,
                    name="",
                    error="PLACE_NOT_FOUND"
                )

            result = data["result"]
            name = result.get("name", "")
            formatted_address = result.get("formatted_address")

            # Get phone number - prefer international format
            raw_phone = (
                result.get("international_phone_number") or
                result.get("formatted_phone_number")
            )

            # Normalize to E.164
            phone_e164 = self._normalize_to_e164(raw_phone)

            if not phone_e164:
                logger.warning(f"Place {name} has no valid phone number")
                return PlaceDetailsResponse(
                    placeId=place_id,
                    name=name,
                    formattedAddress=formatted_address,
                    phoneE164=None,
                    error="NO_PHONE"
                )

            logger.info(f"Place details for {name}: phone={phone_e164}")
            return PlaceDetailsResponse(
                placeId=place_id,
                name=name,
                formattedAddress=formatted_address,
                phoneE164=phone_e164,
                error=None
            )

        except Exception as e:
            logger.error(f"Place details error for {place_id}: {e}")
            return PlaceDetailsResponse(
                placeId=place_id,
                name="",
                error="PLACES_ERROR"
            )

    def _normalize_to_e164(self, phone: Optional[str], default_region: str = "AU") -> Optional[str]:
        """
        Normalize phone number to E.164 format using phonenumbers library.

        E.164 format: +[country code][subscriber number]
        Example: +61412345678

        Handles various input formats:
        - "+61731824583"
        - "07 3182 4583"
        - "(07) 3182 4583"
        - "0731824583"

        Args:
            phone: Raw phone number string
            default_region: Default region code for parsing (default "AU")

        Returns:
            E.164 formatted phone or None if invalid/missing
        """
        if not phone:
            return None

        try:
            # Parse the phone number with default region
            parsed = phonenumbers.parse(phone, default_region)

            # Validate the number
            if not phonenumbers.is_valid_number(parsed):
                logger.debug(f"Invalid phone number: {phone}")
                return None

            # Format to E.164
            e164 = phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.E164
            )

            logger.debug(f"Normalized phone '{phone}' to '{e164}'")
            return e164

        except NumberParseException as e:
            logger.debug(f"Could not parse phone '{phone}': {e}")
            return None
