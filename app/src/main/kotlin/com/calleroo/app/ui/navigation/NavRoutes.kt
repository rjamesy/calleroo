package com.calleroo.app.ui.navigation

import com.calleroo.app.domain.model.AgentType
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

sealed class NavRoutes(val route: String) {
    data object AgentSelect : NavRoutes("agent_select")

    /**
     * Nested navigation graph for task flow (Screens 2-4).
     * TaskSessionViewModel is scoped to this graph for shared state.
     */
    data object TaskFlowGraph : NavRoutes("task_flow/{agentType}/{conversationId}") {
        fun createRoute(agentType: AgentType, conversationId: String): String {
            return "task_flow/${agentType.name}/$conversationId"
        }
    }

    /**
     * Screen 2: Chat - conversation with the assistant.
     * This is the start destination within TaskFlowGraph.
     */
    data object Chat : NavRoutes("chat")

    /**
     * Screen 3: Place Search - find and select a business to call.
     */
    data object PlaceSearch : NavRoutes("place_search/{query}/{area}") {
        fun createRoute(query: String, area: String): String {
            val encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
            val encodedArea = URLEncoder.encode(area, StandardCharsets.UTF_8.toString())
            return "place_search/$encodedQuery/$encodedArea"
        }
    }

    /**
     * Screen 4: Call Summary - review call brief before starting the call.
     */
    data object CallSummary : NavRoutes("call_summary")

    /**
     * Screen 5: Call Status - monitor active call and show results.
     */
    data object CallStatus : NavRoutes("call_status/{callId}") {
        fun createRoute(callId: String): String {
            return "call_status/$callId"
        }
    }
}
