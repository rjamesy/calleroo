package com.calleroo.app.ui.navigation

import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.navigation.navigation
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.ui.screens.agentselect.AgentSelectScreen
import com.calleroo.app.ui.screens.callresults.CallResultsScreen
import com.calleroo.app.ui.screens.callstatus.CallStatusScreen
import com.calleroo.app.ui.screens.callsummary.CallSummaryScreen
import com.calleroo.app.ui.screens.chat.UnifiedChatScreen
import com.calleroo.app.ui.screens.placesearch.PlaceSearchScreen
import com.calleroo.app.ui.screens.scheduledconfirmation.ScheduledConfirmationScreen
import com.calleroo.app.ui.screens.scheduledtasks.ScheduledTasksScreen
import com.calleroo.app.ui.viewmodel.TaskSessionViewModel
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

private const val TAG = "CallerooNavHost"

@Composable
fun CallerooNavHost() {
    val navController = rememberNavController()

    NavHost(
        navController = navController,
        startDestination = NavRoutes.AgentSelect.route
    ) {
        // Screen 1: Agent Selection
        composable(route = NavRoutes.AgentSelect.route) {
            AgentSelectScreen(
                onAgentSelected = { agentType, conversationId ->
                    navController.navigate(
                        NavRoutes.TaskFlowGraph.createRoute(agentType, conversationId)
                    )
                },
                onNavigateToScheduledTasks = {
                    navController.navigate(NavRoutes.ScheduledTasks.route)
                }
            )
        }

        // Scheduled Tasks screen - read-only list of scheduled tasks
        composable(route = NavRoutes.ScheduledTasks.route) {
            ScheduledTasksScreen(
                onNavigateBack = { navController.popBackStack() }
            )
        }

        // Task Flow Nested Navigation Graph (Screens 2-4)
        // TaskSessionViewModel is scoped to this graph for shared state
        navigation(
            route = NavRoutes.TaskFlowGraph.route,
            startDestination = NavRoutes.Chat.route
        ) {
            // Screen 2: Unified Chat
            composable(route = NavRoutes.Chat.route) { backStackEntry ->
                // Get TaskSessionViewModel scoped to the parent TaskFlowGraph
                val parentEntry = remember(backStackEntry) {
                    navController.getBackStackEntry(NavRoutes.TaskFlowGraph.route)
                }
                val taskSession: TaskSessionViewModel = hiltViewModel(parentEntry)

                // Extract agentType and conversationId from parent graph arguments
                val agentTypeName = parentEntry.arguments?.getString("agentType") ?: ""
                val conversationId = parentEntry.arguments?.getString("conversationId") ?: ""
                val agentType = AgentType.valueOf(agentTypeName)

                UnifiedChatScreen(
                    agentType = agentType,
                    conversationId = conversationId,
                    taskSession = taskSession,
                    onNavigateBack = { navController.popBackStack() },
                    onNavigateToPlaceSearch = { query, area ->
                        navController.navigate(
                            NavRoutes.PlaceSearch.createRoute(query, area)
                        )
                    },
                    onNavigateToCallSummary = {
                        // For COMPLETE without place search (e.g., SICK_CALLER with known phone)
                        // Navigate directly to CallSummary
                        Log.i(TAG, "Navigating to CallSummary from Chat (COMPLETE without PlaceSearch)")
                        navController.navigate(NavRoutes.CallSummary.route)
                    }
                )
            }

            // Screen 3: Place Search
            composable(
                route = NavRoutes.PlaceSearch.route,
                arguments = listOf(
                    navArgument("query") { type = NavType.StringType },
                    navArgument("area") { type = NavType.StringType }
                )
            ) { backStackEntry ->
                // Get TaskSessionViewModel scoped to the parent TaskFlowGraph
                val parentEntry = remember(backStackEntry) {
                    navController.getBackStackEntry(NavRoutes.TaskFlowGraph.route)
                }
                val taskSession: TaskSessionViewModel = hiltViewModel(parentEntry)

                PlaceSearchScreen(
                    taskSession = taskSession,
                    onNavigateBack = { navController.popBackStack() },
                    onPlaceResolved = { resolvedState ->
                        // Set resolved place in task session
                        taskSession.setResolvedPlace(resolvedState.toResolvedPlace())

                        // Navigate to Call Summary screen
                        Log.i(TAG, "Navigating to CallSummary: " +
                                "name=${resolvedState.businessName}, " +
                                "phone=${resolvedState.phoneE164}")
                        navController.navigate(NavRoutes.CallSummary.route)
                    }
                )
            }

            // Screen 4: Call Summary
            composable(route = NavRoutes.CallSummary.route) { backStackEntry ->
                // Get TaskSessionViewModel scoped to the parent TaskFlowGraph
                val parentEntry = remember(backStackEntry) {
                    navController.getBackStackEntry(NavRoutes.TaskFlowGraph.route)
                }
                val taskSession: TaskSessionViewModel = hiltViewModel(parentEntry)

                // Extract agentType from parent graph arguments for passing to CallStatus
                val agentTypeName = parentEntry.arguments?.getString("agentType") ?: ""

                CallSummaryScreen(
                    taskSession = taskSession,
                    onNavigateBack = {
                        // Clear resolved place when going back to allow re-selection
                        taskSession.clearResolvedPlace()
                        navController.popBackStack()
                    },
                    onNavigateToChat = {
                        // Navigate back to chat to fix missing fields
                        navController.popBackStack(NavRoutes.Chat.route, inclusive = false)
                    },
                    onNavigateToCallStatus = { callId ->
                        Log.i(TAG, "Navigating to CallStatus: callId=$callId, agentType=$agentTypeName")
                        navController.navigate(NavRoutes.CallStatus.createRoute(callId, agentTypeName))
                    },
                    onNavigateToScheduledConfirmation = { agentType, scheduledTimeUtc ->
                        Log.i(TAG, "Navigating to ScheduledConfirmation: agentType=$agentType, scheduledTime=$scheduledTimeUtc")
                        navController.navigate(
                            NavRoutes.ScheduledConfirmation.createRoute(agentType, scheduledTimeUtc)
                        )
                    }
                )
            }

            // Screen 5: Call Status - polls for call completion
            composable(
                route = NavRoutes.CallStatus.route,
                arguments = listOf(
                    navArgument("callId") { type = NavType.StringType },
                    navArgument("agentType") { type = NavType.StringType }
                )
            ) { _ ->
                // callId and agentType are retrieved from SavedStateHandle in CallStatusViewModel

                CallStatusScreen(
                    onNavigateToHome = {
                        // Navigate back to Agent Select, clearing the entire task flow
                        navController.popBackStack(
                            route = NavRoutes.AgentSelect.route,
                            inclusive = false
                        )
                    },
                    onNavigateToResults = { resultCallId, resultAgentType ->
                        Log.i(TAG, "Navigating to CallResults: callId=$resultCallId, agentType=$resultAgentType")
                        navController.navigate(
                            NavRoutes.CallResults.createRoute(resultCallId, resultAgentType)
                        ) {
                            // Replace CallStatus in the back stack
                            popUpTo(NavRoutes.CallStatus.route) { inclusive = true }
                        }
                    }
                )
            }

            // Screen 6: Call Results - displays formatted call results
            composable(
                route = NavRoutes.CallResults.route,
                arguments = listOf(
                    navArgument("callId") { type = NavType.StringType },
                    navArgument("agentType") { type = NavType.StringType }
                )
            ) {
                CallResultsScreen(
                    onNavigateToHome = {
                        // Navigate back to Agent Select, clearing the entire task flow
                        navController.popBackStack(
                            route = NavRoutes.AgentSelect.route,
                            inclusive = false
                        )
                    }
                )
            }

            // Screen: Scheduled Confirmation - shown after successfully scheduling a call
            composable(
                route = NavRoutes.ScheduledConfirmation.route,
                arguments = listOf(
                    navArgument("agentType") { type = NavType.StringType },
                    navArgument("scheduledTimeUtc") { type = NavType.StringType }
                )
            ) { backStackEntry ->
                val agentType = backStackEntry.arguments?.getString("agentType") ?: ""
                val scheduledTimeUtc = URLDecoder.decode(
                    backStackEntry.arguments?.getString("scheduledTimeUtc") ?: "",
                    StandardCharsets.UTF_8.toString()
                )

                ScheduledConfirmationScreen(
                    agentType = agentType,
                    scheduledTimeUtc = scheduledTimeUtc,
                    onNavigateToHome = {
                        // Navigate back to Agent Select, clearing the entire task flow
                        // If popBackStack fails (AgentSelect not on stack), navigate directly
                        val popped = navController.popBackStack(
                            route = NavRoutes.AgentSelect.route,
                            inclusive = false
                        )
                        if (!popped) {
                            navController.navigate(NavRoutes.AgentSelect.route) {
                                popUpTo(navController.graph.startDestinationId) { inclusive = true }
                                launchSingleTop = true
                            }
                        }
                    }
                )
            }
        }
    }
}
