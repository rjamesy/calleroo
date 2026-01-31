package com.calleroo.app.ui.screens.callsummary

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.ui.viewmodel.TaskSessionViewModel
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CallSummaryScreen(
    taskSession: TaskSessionViewModel,
    onNavigateBack: () -> Unit,
    onNavigateToChat: () -> Unit,
    onNavigateToCallStatus: (String) -> Unit,
    onNavigateToScheduledConfirmation: (String, String) -> Unit,
    viewModel: CallSummaryViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsState()
    val navigateToCallStatus by viewModel.navigateToCallStatus.collectAsState()
    val navigateToScheduledConfirmation by viewModel.navigateToScheduledConfirmation.collectAsState()

    // Snackbar for error messages
    val snackbarHostState = remember { SnackbarHostState() }

    // Initialize ViewModel with task session on first composition
    LaunchedEffect(Unit) {
        viewModel.initialize(taskSession)
    }

    // Handle navigation to CallStatus screen
    LaunchedEffect(navigateToCallStatus) {
        navigateToCallStatus?.let { callId ->
            viewModel.clearNavigateToCallStatus()
            onNavigateToCallStatus(callId)
        }
    }

    // Handle navigation to ScheduledConfirmation screen
    LaunchedEffect(navigateToScheduledConfirmation) {
        navigateToScheduledConfirmation?.let { (agentType, scheduledTimeUtc) ->
            viewModel.clearNavigateToScheduledConfirmation()
            onNavigateToScheduledConfirmation(agentType, scheduledTimeUtc)
        }
    }

    // Handle snackbar messages
    LaunchedEffect(Unit) {
        viewModel.snackbarMessage.collect { message ->
            snackbarHostState.showSnackbar(message)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Call Summary") },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(
                            imageVector = Icons.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (state is CallSummaryState.ReadyToReview) {
                val reviewState = state as CallSummaryState.ReadyToReview
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    tonalElevation = 3.dp,
                    shadowElevation = 8.dp
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        OutlinedButton(
                            onClick = onNavigateBack,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("Back")
                        }
                        Button(
                            onClick = { viewModel.startCall() },
                            modifier = Modifier.weight(1f),
                            enabled = reviewState.canStartCall
                        ) {
                            Icon(
                                imageVector = Icons.Default.Call,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Start Call")
                        }
                    }
                }
            }
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            when (val currentState = state) {
                is CallSummaryState.LoadingBrief -> {
                    LoadingContent()
                }

                is CallSummaryState.ReadyToReview -> {
                    ReadyToReviewContent(
                        state = currentState,
                        agentType = taskSession.agentType,
                        onToggleChecklistItem = viewModel::toggleChecklistItem,
                        onUpdateDisclosure = viewModel::updateDisclosure,
                        onUpdateFallbacks = viewModel::updateFallbacks,
                        onEditNumber = viewModel::startEditingNumber,
                        onNavigateToChat = onNavigateToChat,
                        onDateSelected = viewModel::updateScheduleDate,
                        onTimeSelected = viewModel::updateScheduleTime,
                        onScheduleCall = viewModel::scheduleCall
                    )
                }

                is CallSummaryState.EditingNumber -> {
                    EditNumberDialog(
                        state = currentState,
                        onInputChange = viewModel::updatePhoneInput,
                        onConfirm = viewModel::confirmPhoneEdit,
                        onCancel = viewModel::cancelPhoneEdit
                    )
                }

                is CallSummaryState.StartingCall -> {
                    LoadingContent(message = "Starting call...")
                }

                is CallSummaryState.SchedulingCall -> {
                    LoadingContent(message = "Scheduling call...")
                }

                is CallSummaryState.Error -> {
                    ErrorContent(
                        message = currentState.message,
                        onRetry = viewModel::retry
                    )
                }
            }
        }
    }
}

@Composable
private fun LoadingContent(message: String = "Loading call brief...") {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            CircularProgressIndicator()
            Text(
                text = message,
                style = MaterialTheme.typography.bodyLarge
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReadyToReviewContent(
    state: CallSummaryState.ReadyToReview,
    agentType: AgentType,
    onToggleChecklistItem: (Int) -> Unit,
    onUpdateDisclosure: (Boolean?, Boolean?) -> Unit,
    onUpdateFallbacks: (Boolean?, Boolean?, Boolean?, Boolean?, Boolean?) -> Unit,
    onEditNumber: () -> Unit,
    onNavigateToChat: () -> Unit,
    onDateSelected: (LocalDate?) -> Unit,
    onTimeSelected: (LocalTime?) -> Unit,
    onScheduleCall: () -> Unit
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Business Card
        item {
            BusinessCard(
                businessName = state.place.businessName,
                address = state.place.formattedAddress,
                phone = state.normalizedPhoneE164,
                onEditNumber = onEditNumber
            )
        }

        // Required Fields Blocker (if any missing)
        if (state.hasBlocker) {
            item {
                BlockerCard(
                    missingFields = state.requiredFieldsMissing,
                    onNavigateToChat = onNavigateToChat
                )
            }
        }

        // Objective Card
        item {
            ObjectiveCard(objective = state.objective)
        }

        // Script Preview Card
        item {
            ScriptPreviewCard(scriptPreview = state.scriptPreview)
        }

        // Disclosure Toggles
        item {
            DisclosureCard(
                disclosure = state.disclosure,
                onUpdateDisclosure = onUpdateDisclosure
            )
        }

        // Fallback Toggles (conditional by agent type)
        item {
            FallbackCard(
                agentType = agentType,
                fallbacks = state.fallbacks,
                onUpdateFallbacks = onUpdateFallbacks
            )
        }

        // Checklist
        item {
            ChecklistCard(
                checklist = state.checklist,
                onToggleItem = onToggleChecklistItem
            )
        }

        // Schedule Call Card (only if scheduler is available)
        if (state.isSchedulerAvailable) {
            item {
                ScheduleCallCard(
                    selectedDate = state.scheduleDate,
                    selectedTime = state.scheduleTime,
                    canSchedule = state.canScheduleCall,
                    onDateSelected = onDateSelected,
                    onTimeSelected = onTimeSelected,
                    onScheduleCall = onScheduleCall
                )
            }
        }

        // Bottom spacing for sticky CTA
        item {
            Spacer(modifier = Modifier.height(80.dp))
        }
    }
}

@Composable
private fun BusinessCard(
    businessName: String,
    address: String?,
    phone: String,
    onEditNumber: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.Place,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = businessName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f)
                )
            }

            if (!address.isNullOrBlank()) {
                Text(
                    text = address,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = phone,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium
                )
                TextButton(onClick = onEditNumber) {
                    Icon(
                        imageVector = Icons.Default.Edit,
                        contentDescription = null,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Edit")
                }
            }
        }
    }
}

@Composable
private fun BlockerCard(
    missingFields: List<String>,
    onNavigateToChat: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Missing Required Information",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onErrorContainer
                )
            }

            Text(
                text = "Missing: ${missingFields.joinToString(", ")}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onErrorContainer
            )

            Text(
                text = "Go back to chat to provide this information.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer
            )

            Button(
                onClick = onNavigateToChat,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error
                )
            ) {
                Text("Back to Chat")
            }
        }
    }
}

@Composable
private fun ObjectiveCard(objective: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Objective",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = objective,
                style = MaterialTheme.typography.bodyLarge
            )
        }
    }
}

@Composable
private fun ScriptPreviewCard(scriptPreview: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Call Script Preview",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(8.dp))
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(8.dp)
            ) {
                Text(
                    text = scriptPreview,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(12.dp)
                )
            }
        }
    }
}

@Composable
private fun DisclosureCard(
    disclosure: com.calleroo.app.domain.model.CallBriefDisclosure,
    onUpdateDisclosure: (Boolean?, Boolean?) -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Disclosure Settings",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(8.dp))

            ToggleRow(
                label = "Share my name",
                checked = disclosure.nameShare,
                onCheckedChange = { onUpdateDisclosure(it, null) }
            )

            ToggleRow(
                label = "Share my phone number",
                checked = disclosure.phoneShare,
                onCheckedChange = { onUpdateDisclosure(null, it) }
            )
        }
    }
}

@Composable
private fun FallbackCard(
    agentType: AgentType,
    fallbacks: com.calleroo.app.domain.model.CallBriefFallbacks,
    onUpdateFallbacks: (Boolean?, Boolean?, Boolean?, Boolean?, Boolean?) -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Fallback Options",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(8.dp))

            when (agentType) {
                AgentType.STOCK_CHECKER -> {
                    ToggleRow(
                        label = "Ask for ETA if out of stock",
                        checked = fallbacks.askETA ?: false,
                        onCheckedChange = { onUpdateFallbacks(it, null, null, null, null) }
                    )
                    ToggleRow(
                        label = "Ask about nearest store",
                        checked = fallbacks.askNearestStore ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, it, null, null, null) }
                    )
                }

                AgentType.RESTAURANT_RESERVATION -> {
                    ToggleRow(
                        label = "Retry if no answer",
                        checked = fallbacks.retryIfNoAnswer ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, null, it, null, null) }
                    )
                    ToggleRow(
                        label = "Retry if busy",
                        checked = fallbacks.retryIfBusy ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, null, null, it, null) }
                    )
                    ToggleRow(
                        label = "Leave voicemail",
                        checked = fallbacks.leaveVoicemail ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, null, null, null, it) }
                    )
                }

                AgentType.SICK_CALLER -> {
                    ToggleRow(
                        label = "Leave voicemail",
                        checked = fallbacks.leaveVoicemail ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, null, null, null, it) }
                    )
                }

                AgentType.CANCEL_APPOINTMENT -> {
                    ToggleRow(
                        label = "Leave voicemail",
                        checked = fallbacks.leaveVoicemail ?: false,
                        onCheckedChange = { onUpdateFallbacks(null, null, null, null, it) }
                    )
                }
            }
        }
    }
}

@Composable
private fun ToggleRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f)
        )
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
    }
}

@Composable
private fun ChecklistCard(
    checklist: List<ChecklistItem>,
    onToggleItem: (Int) -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Pre-call Checklist",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Text(
                text = "Check all items to enable Start Call",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(8.dp))

            checklist.forEachIndexed { index, item ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Checkbox(
                        checked = item.checked,
                        onCheckedChange = { onToggleItem(index) }
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = item.text,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f)
                    )
                    if (item.checked) {
                        Icon(
                            imageVector = Icons.Default.Check,
                            contentDescription = "Checked",
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(20.dp)
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun EditNumberDialog(
    state: CallSummaryState.EditingNumber,
    onInputChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onCancel: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Edit Phone Number") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = state.currentInput,
                    onValueChange = onInputChange,
                    label = { Text("Phone Number") },
                    isError = state.error != null,
                    supportingText = {
                        when {
                            state.error != null -> Text(state.error)
                            state.previewE164 != null -> Text("Will be formatted as: ${state.previewE164}")
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = state.previewE164 != null
            ) {
                Text("Confirm")
            }
        },
        dismissButton = {
            TextButton(onClick = onCancel) {
                Text("Cancel")
            }
        }
    )
}

@Composable
private fun ErrorContent(
    message: String,
    onRetry: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.padding(32.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(48.dp)
            )
            Text(
                text = "Something went wrong",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Button(onClick = onRetry) {
                Text("Retry")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ScheduleCallCard(
    selectedDate: LocalDate?,
    selectedTime: LocalTime?,
    canSchedule: Boolean,
    onDateSelected: (LocalDate?) -> Unit,
    onTimeSelected: (LocalTime?) -> Unit,
    onScheduleCall: () -> Unit
) {
    var showDatePicker by remember { mutableStateOf(false) }
    var showTimePicker by remember { mutableStateOf(false) }

    val dateFormatter = remember { DateTimeFormatter.ofPattern("EEE, MMM d, yyyy") }
    val timeFormatter = remember { DateTimeFormatter.ofPattern("h:mm a") }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.Schedule,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.secondary
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Schedule for Later",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
            }

            Text(
                text = "Instead of calling now, schedule this call for a specific time.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                // Date picker button
                OutlinedButton(
                    onClick = { showDatePicker = true },
                    modifier = Modifier.weight(1f)
                ) {
                    Icon(
                        imageVector = Icons.Default.DateRange,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = selectedDate?.format(dateFormatter) ?: "Select Date"
                    )
                }

                // Time picker button
                OutlinedButton(
                    onClick = { showTimePicker = true },
                    modifier = Modifier.weight(1f)
                ) {
                    Icon(
                        imageVector = Icons.Default.Schedule,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = selectedTime?.format(timeFormatter) ?: "Select Time"
                    )
                }
            }

            Button(
                onClick = onScheduleCall,
                modifier = Modifier.fillMaxWidth(),
                enabled = canSchedule,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.secondary
                )
            ) {
                Icon(
                    imageVector = Icons.Default.Schedule,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Schedule Call")
            }
        }
    }

    // Date Picker Dialog
    if (showDatePicker) {
        val datePickerState = rememberDatePickerState(
            initialSelectedDateMillis = selectedDate?.atStartOfDay(ZoneId.systemDefault())
                ?.toInstant()?.toEpochMilli()
                ?: System.currentTimeMillis()
        )

        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        datePickerState.selectedDateMillis?.let { millis ->
                            val date = Instant.ofEpochMilli(millis)
                                .atZone(ZoneId.systemDefault())
                                .toLocalDate()
                            onDateSelected(date)
                        }
                        showDatePicker = false
                    }
                ) {
                    Text("OK")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) {
                    Text("Cancel")
                }
            }
        ) {
            DatePicker(state = datePickerState)
        }
    }

    // Time Picker Dialog
    if (showTimePicker) {
        val timePickerState = rememberTimePickerState(
            initialHour = selectedTime?.hour ?: 9,
            initialMinute = selectedTime?.minute ?: 0
        )

        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            title = { Text("Select Time") },
            text = {
                Box(
                    modifier = Modifier.fillMaxWidth(),
                    contentAlignment = Alignment.Center
                ) {
                    TimePicker(state = timePickerState)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onTimeSelected(LocalTime.of(timePickerState.hour, timePickerState.minute))
                        showTimePicker = false
                    }
                ) {
                    Text("OK")
                }
            },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}
