package com.calleroo.app.domain.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class AgentType {
    @SerialName("STOCK_CHECKER")
    STOCK_CHECKER,

    @SerialName("RESTAURANT_RESERVATION")
    RESTAURANT_RESERVATION,

    @SerialName("SICK_CALLER")
    SICK_CALLER,

    @SerialName("CANCEL_APPOINTMENT")
    CANCEL_APPOINTMENT;

    val displayName: String
        get() = when (this) {
            STOCK_CHECKER -> "Stock Check"
            RESTAURANT_RESERVATION -> "Book Restaurant"
            SICK_CALLER -> "Call in Sick"
            CANCEL_APPOINTMENT -> "Cancel Appointment"
        }

    val description: String
        get() = when (this) {
            STOCK_CHECKER -> "Check product availability at retailers"
            RESTAURANT_RESERVATION -> "Book a table at a restaurant"
            SICK_CALLER -> "Notify your workplace you're unwell"
            CANCEL_APPOINTMENT -> "Cancel an existing booking for you"
        }
}
