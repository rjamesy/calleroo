package com.calleroo.app.ui.screens.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.calleroo.app.domain.model.AgentType
import com.calleroo.app.domain.model.Choice
import com.calleroo.app.domain.model.ConfirmationCard
import com.calleroo.app.domain.model.InputType
import com.calleroo.app.domain.model.NextAction
import com.calleroo.app.domain.model.Question
import com.calleroo.app.domain.model.ResolvedPlace
import com.calleroo.app.ui.viewmodel.TaskSessionViewModel
import com.calleroo.app.util.PhoneUtils
import com.calleroo.app.util.UnifiedConversationGuard
import kotlinx.coroutines.flow.collectLatest
import kotlinx.serialization.json.jsonPrimitive

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UnifiedChatScreen(
    agentType: AgentType,
    conversationId: String,
    taskSession: TaskSessionViewModel,
    onNavigateBack: () -> Unit,
    onNavigateToPlaceSearch: (query: String, area: String) -> Unit,
    onNavigateToCallSummary: () -> Unit,
    viewModel: UnifiedChatViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val navigateToPlaceSearch by viewModel.navigateToPlaceSearch.collectAsStateWithLifecycle()
    val navigateToCallSummary by viewModel.navigateToCallSummary.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val listState = rememberLazyListState()

    // ✅ FIX 1: Only init session ONCE per conversation (don't wipe slots on recomposition)
    LaunchedEffect(Unit) {
        if (taskSession.conversationId != conversationId) {
            taskSession.initSession(conversationId, agentType)
            viewModel.initialize(agentType, conversationId)
        }
    }

    // ✅ FIX 2: Continuous slot sync (no missed updates under load)
    LaunchedEffect(Unit) {
        snapshotFlow { uiState.slots }
            .collectLatest { slots ->
                taskSession.updateSlots(slots)
            }
    }

    // Auto-scroll to bottom when new messages arrive
    LaunchedEffect(uiState.messages.size) {
        if (uiState.messages.isNotEmpty()) {
            listState.animateScrollToItem(uiState.messages.size - 1)
        }
    }

    // Show error as snackbar
    LaunchedEffect(uiState.error) {
        uiState.error?.let { error ->
            snackbarHostState.showSnackbar(error)
            viewModel.clearError()
        }
    }

    // Navigate to Place Search when backend returns FIND_PLACE
    LaunchedEffect(uiState.nextAction, uiState.placeSearchParams) {
        if (uiState.nextAction == NextAction.FIND_PLACE && uiState.placeSearchParams != null) {
            val params = uiState.placeSearchParams
            if (params != null) {
                viewModel.clearPlaceSearchParams()
                val safeQuery = params.query.ifBlank { "business" }
                val safeArea = params.area.ifBlank { "Australia" }
                onNavigateToPlaceSearch(safeQuery, safeArea)
            }
        }
    }

    // Navigate to Place Search when Continue button is clicked (for FIND_PLACE)
    LaunchedEffect(navigateToPlaceSearch) {
        navigateToPlaceSearch?.let { (query, area) ->
            viewModel.clearNavigateToPlaceSearch()
            onNavigateToPlaceSearch(query, area)
        }
    }

    // Navigate to Call Summary when Continue button is clicked (for COMPLETE)
    // For direct-phone agents (SICK_CALLER), synthesize ResolvedPlace from slots
    LaunchedEffect(navigateToCallSummary) {
        if (navigateToCallSummary) {
            viewModel.clearNavigateToCallSummary()

            if (agentType == AgentType.SICK_CALLER) {
                val slots = uiState.slots

                val employerName = slots["employer_name"]?.jsonPrimitive?.content
                    ?.takeIf { it.isNotBlank() }
                    ?: "Work"

                val rawPhone = slots["employer_phone"]?.jsonPrimitive?.content ?: ""
                val phoneE164 = PhoneUtils.toE164(rawPhone)

                if (phoneE164 != null) {
                    val manualPlace = ResolvedPlace(
                        placeId = "manual:sick_caller:${conversationId}",
                        businessName = employerName,
                        formattedAddress = null,
                        phoneE164 = phoneE164
                    )
                    taskSession.setResolvedPlace(manualPlace)
                    onNavigateToCallSummary()
                } else {
                    snackbarHostState.showSnackbar(
                        "Invalid phone number. Please check the employer phone and try again."
                    )
                }
            } else {
                onNavigateToCallSummary()
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = agentType.displayName,
                        fontWeight = FontWeight.SemiBold
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(
                            imageVector = Icons.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        },
        snackbarHost = {
            SnackbarHost(snackbarHostState) { data ->
                Snackbar(
                    snackbarData = data,
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer
                )
            }
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .imePadding()
                .navigationBarsPadding()
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(uiState.messages, key = { it.id }) { message ->
                    ChatBubble(message = message)
                }

                if (uiState.isLoading) {
                    item { LoadingIndicator() }
                }
            }

            uiState.confirmationCard?.let { card ->
                if (uiState.showConfirmationCard || uiState.isConfirmationSubmitting) {
                    ConfirmationCardUi(
                        card = card,
                        onConfirm = { viewModel.handleConfirmation(true) },
                        onReject = { viewModel.handleConfirmation(false) },
                        enabled = !uiState.isLoading && !uiState.isConfirmationSubmitting,
                        isSubmitting = uiState.isConfirmationSubmitting
                    )
                }
            }

            if (uiState.showContinueButton) {
                ContinueButton(
                    onClick = {
                        // FIX 3: Handle SICK_CALLER directly (no PlaceSearch step)
                        if (agentType == AgentType.SICK_CALLER) {
                            // Sync slots before navigation
                            taskSession.updateSlots(uiState.slots)
                            viewModel.triggerNavigateToCallSummary()
                        } else {
                            viewModel.handleContinue()
                        }
                    }
                )
            }

            val currentQuestion = uiState.currentQuestion
            val choices = currentQuestion?.choices
            if (!choices.isNullOrEmpty() && !uiState.showConfirmationCard && !uiState.showContinueButton) {
                UnifiedConversationGuard.assertChoicesFromBackend(
                    choices = choices,
                    backendProvided = true
                )

                ChoiceChips(
                    choices = choices,
                    onChoiceSelected = { choice ->
                        // FIX 1: Persist CHOICE locally before sending to backend
                        // This ensures slots like reason_category are saved immediately
                        val field = uiState.currentQuestion?.field
                        if (!field.isNullOrBlank()) {
                            viewModel.injectSlot(field, choice.value)
                        }

                        viewModel.sendMessage(choice.value)
                    },
                    enabled = !uiState.isLoading
                )
            }

            if (!uiState.showContinueButton) {
                ChatInputBar(
                    question = uiState.currentQuestion,
                    onSend = { userInput ->
                        // FIX 5: Persist TEXT input locally before sending to backend
                        // This ensures slots like caller_name are saved immediately
                        val field = uiState.currentQuestion?.field
                        if (!field.isNullOrBlank() && userInput.isNotBlank()) {
                            viewModel.injectSlot(field, userInput)
                        }
                        viewModel.sendMessage(userInput)
                    },
                    onFindNumber = {
                        // ✅ FIX 3: use jsonPrimitive.content (avoid quoted strings / "null")
                        val employerName = uiState.slots["employer_name"]
                            ?.jsonPrimitive
                            ?.content
                            ?.takeIf { it.isNotBlank() }
                            ?: "business"

                        val area = uiState.slots["location"]
                            ?.jsonPrimitive
                            ?.content
                            ?.takeIf { it.isNotBlank() }
                            ?: "Australia"

                        onNavigateToPlaceSearch(employerName, area)
                    },
                    enabled = !uiState.isLoading && !uiState.showConfirmationCard
                )
            }
        }
    }
}

@Composable
private fun ChatBubble(message: ChatMessageUi) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (message.isUser) Arrangement.End else Arrangement.Start
    ) {
        Box(
            modifier = Modifier
                .widthIn(max = 300.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 16.dp,
                        topEnd = 16.dp,
                        bottomStart = if (message.isUser) 16.dp else 4.dp,
                        bottomEnd = if (message.isUser) 4.dp else 16.dp
                    )
                )
                .background(
                    if (message.isUser) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.surfaceVariant
                )
                .padding(12.dp)
        ) {
            Text(
                text = message.content,
                style = MaterialTheme.typography.bodyMedium,
                color = if (message.isUser) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun LoadingIndicator() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Start
    ) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(16.dp)
        ) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp
            )
        }
    }
}

@Composable
private fun ConfirmationCardUi(
    card: ConfirmationCard,
    onConfirm: () -> Unit,
    onReject: () -> Unit,
    enabled: Boolean,
    isSubmitting: Boolean = false
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = card.title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )

            Spacer(modifier = Modifier.height(12.dp))

            card.lines.forEach { line ->
                Text(
                    text = line,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.9f)
                )
                Spacer(modifier = Modifier.height(4.dp))
            }

            Spacer(modifier = Modifier.height(16.dp))

            if (isSubmitting) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = "Calling...",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    OutlinedButton(
                        onClick = onReject,
                        enabled = enabled,
                        modifier = Modifier.weight(1f)
                    ) { Text(card.rejectLabel) }

                    Button(
                        onClick = onConfirm,
                        enabled = enabled,
                        modifier = Modifier.weight(1f)
                    ) { Text(card.confirmLabel) }
                }
            }
        }
    }
}

@Composable
private fun ContinueButton(onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
    ) {
        Button(
            onClick = onClick,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp)
        ) {
            Text(
                text = "Continue",
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun ChoiceChips(
    choices: List<Choice>,
    onChoiceSelected: (Choice) -> Unit,
    enabled: Boolean
) {
    FlowRow(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        choices.forEach { choice ->
            FilterChip(
                selected = false,
                onClick = { onChoiceSelected(choice) },
                enabled = enabled,
                label = { Text(choice.label) },
                colors = FilterChipDefaults.filterChipColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    labelColor = MaterialTheme.colorScheme.onSurfaceVariant
                )
            )
        }
    }
}

@Composable
private fun ChatInputBar(
    question: Question?,
    onSend: (String) -> Unit,
    onFindNumber: () -> Unit,
    enabled: Boolean
) {
    var inputText by remember { mutableStateOf("") }

    val isPhoneInput = question?.inputType == InputType.PHONE
    val keyboardType = when (question?.inputType) {
        InputType.NUMBER -> KeyboardType.Number
        InputType.PHONE -> KeyboardType.Phone
        InputType.DATE -> KeyboardType.Text
        InputType.TIME -> KeyboardType.Text
        else -> KeyboardType.Text
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
    ) {
        if (isPhoneInput && enabled) {
            OutlinedButton(
                onClick = onFindNumber,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.primary
                )
            ) {
                Icon(
                    imageVector = Icons.Filled.Search,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Find number")
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Bottom
        ) {
            OutlinedTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier.weight(1f),
                placeholder = {
                    Text(
                        text = question?.text ?: "Type a message...",
                        style = MaterialTheme.typography.bodyMedium
                    )
                },
                enabled = enabled,
                singleLine = false,
                maxLines = 4,
                keyboardOptions = KeyboardOptions(
                    capitalization = if (isPhoneInput) KeyboardCapitalization.None else KeyboardCapitalization.Sentences,
                    keyboardType = keyboardType,
                    imeAction = ImeAction.Send
                ),
                keyboardActions = KeyboardActions(
                    onSend = {
                        if (inputText.isNotBlank()) {
                            onSend(inputText)
                            inputText = ""
                        }
                    }
                ),
                shape = RoundedCornerShape(24.dp)
            )

            Spacer(modifier = Modifier.width(8.dp))

            IconButton(
                onClick = {
                    if (inputText.isNotBlank()) {
                        onSend(inputText)
                        inputText = ""
                    }
                },
                enabled = enabled && inputText.isNotBlank(),
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(
                        if (enabled && inputText.isNotBlank()) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.surfaceVariant
                    )
            ) {
                Icon(
                    imageVector = Icons.Filled.Send,
                    contentDescription = "Send",
                    tint = if (enabled && inputText.isNotBlank()) MaterialTheme.colorScheme.onPrimary
                    else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                )
            }
        }
    }
}