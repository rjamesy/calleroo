package com.calleroo.app.network

import com.calleroo.app.domain.model.CallBriefRequestV2
import com.calleroo.app.domain.model.CallBriefResponseV2
import com.calleroo.app.domain.model.CallResultFormatRequestV1
import com.calleroo.app.domain.model.CallResultFormatResponseV1
import com.calleroo.app.domain.model.CallStartRequestV2
import com.calleroo.app.domain.model.CallStartResponseV2
import com.calleroo.app.domain.model.CallStartRequestV3
import com.calleroo.app.domain.model.CallStartResponseV3
import com.calleroo.app.domain.model.CallStatusResponseV1
import com.calleroo.app.domain.model.ConversationRequest
import com.calleroo.app.domain.model.ConversationResponse
import com.calleroo.app.domain.model.PlaceDetailsRequest
import com.calleroo.app.domain.model.PlaceDetailsResponse
import com.calleroo.app.domain.model.PlaceSearchRequest
import com.calleroo.app.domain.model.PlaceSearchResponse
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface ConversationApi {

    @POST("/conversation/next")
    suspend fun nextTurn(@Body request: ConversationRequest): ConversationResponse

    @POST("/places/search")
    suspend fun placesSearch(@Body request: PlaceSearchRequest): PlaceSearchResponse

    @POST("/places/details")
    suspend fun placesDetails(@Body request: PlaceDetailsRequest): PlaceDetailsResponse

    @POST("/call/brief")
    suspend fun callBrief(@Body request: CallBriefRequestV2): CallBriefResponseV2

    @POST("/call/start/v2")
    suspend fun callStart(@Body request: CallStartRequestV2): CallStartResponseV2

    // Step 4: Real Twilio Calls
    @POST("/call/start")
    suspend fun callStartV3(@Body request: CallStartRequestV3): CallStartResponseV3

    @GET("/call/status/{callId}")
    suspend fun getCallStatus(@Path("callId") callId: String): CallStatusResponseV1

    // Post-call result formatting
    @POST("/call/result/format")
    suspend fun formatCallResult(@Body request: CallResultFormatRequestV1): CallResultFormatResponseV1
}
