package com.calleroo.app.util

import android.util.Log
import com.google.i18n.phonenumbers.NumberParseException
import com.google.i18n.phonenumbers.PhoneNumberUtil

private const val TAG = "PhoneUtils"

/**
 * Utility for phone number normalization.
 * Converts Australian mobile numbers (04xx...) to E.164 format (+614...).
 */
object PhoneUtils {

    private val phoneNumberUtil: PhoneNumberUtil by lazy {
        PhoneNumberUtil.getInstance()
    }

    /**
     * Parse and format a phone number to E.164 format.
     *
     * @param rawPhone The raw phone number (e.g., "0413123456", "+61413123456")
     * @param defaultRegion The default region for parsing (default: "AU")
     * @return The E.164 formatted number (e.g., "+61413123456") or null if invalid
     */
    fun toE164(rawPhone: String, defaultRegion: String = "AU"): String? {
        if (rawPhone.isBlank()) {
            Log.w(TAG, "toE164: empty input")
            return null
        }

        return try {
            val parsed = phoneNumberUtil.parse(rawPhone.trim(), defaultRegion)
            if (phoneNumberUtil.isValidNumber(parsed)) {
                val e164 = phoneNumberUtil.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164)
                Log.d(TAG, "toE164: '$rawPhone' -> '$e164'")
                e164
            } else {
                Log.w(TAG, "toE164: invalid number '$rawPhone'")
                null
            }
        } catch (e: NumberParseException) {
            Log.w(TAG, "toE164: failed to parse '$rawPhone': ${e.message}")
            null
        }
    }
}
