package com.calleroo.app.ui.screens.placesearch

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.calleroo.app.domain.model.PlaceCandidate
import com.calleroo.app.ui.viewmodel.TaskSessionViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaceSearchScreen(
    taskSession: TaskSessionViewModel,
    onNavigateBack: () -> Unit,
    onPlaceResolved: (PlaceSearchState.Resolved) -> Unit,
    viewModel: PlaceSearchViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val showManualEntryDialog by viewModel.showManualEntryDialog.collectAsStateWithLifecycle()
    val manualEntryError by viewModel.manualEntryError.collectAsStateWithLifecycle()

    // Manual entry dialog
    if (showManualEntryDialog) {
        ManualEntryDialog(
            initialName = viewModel.query,
            error = manualEntryError,
            onDismiss = { viewModel.closeManualEntry() },
            onSubmit = { name, phone -> viewModel.submitManualEntry(name, phone) }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "Choose the place to call",
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
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            // Subtitle with search info
            SearchHeader(
                query = viewModel.query,
                area = viewModel.area
            )

            // Main content based on state
            Box(modifier = Modifier.weight(1f)) {
                when (val currentState = state) {
                    is PlaceSearchState.Loading -> {
                        LoadingContent(
                            passNumber = currentState.passNumber,
                            radiusKm = currentState.radiusKm,
                            message = currentState.message
                        )
                    }

                    is PlaceSearchState.Results -> {
                        ResultsContent(
                            state = currentState,
                            onSelectCandidate = { viewModel.selectCandidate(it) },
                            onConfirmSelection = { viewModel.confirmSelection() },
                            onExpandRadius = { viewModel.expandRadius() },
                            onManualEntry = { viewModel.openManualEntry() }
                        )
                    }

                    is PlaceSearchState.NoResults -> {
                        NoResultsContent(
                            state = currentState,
                            onExpandRadius = { viewModel.expandRadius() },
                            onManualEntry = { viewModel.openManualEntry() },
                            onGoBack = onNavigateBack
                        )
                    }

                    is PlaceSearchState.Error -> {
                        ErrorContent(
                            message = currentState.message,
                            onRetry = { viewModel.retry() },
                            onManualEntry = { viewModel.openManualEntry() },
                            onBackToResults = { viewModel.backToResults() },
                            onGoBack = onNavigateBack
                        )
                    }

                    is PlaceSearchState.Resolving -> {
                        ResolvingContent(
                            placeName = currentState.placeName
                        )
                    }

                    is PlaceSearchState.Resolved -> {
                        ResolvedContent(
                            state = currentState,
                            onContinue = { onPlaceResolved(currentState) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchHeader(
    query: String,
    area: String
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Default.Search,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "Searching for \"$query\" near $area",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun LoadingContent(
    passNumber: Int,
    radiusKm: Int,
    message: String
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Within ${radiusKm}km (pass $passNumber of 3)",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
            )
        }
    }
}

@Composable
private fun ResultsContent(
    state: PlaceSearchState.Results,
    onSelectCandidate: (PlaceCandidate) -> Unit,
    onConfirmSelection: () -> Unit,
    onExpandRadius: () -> Unit,
    onManualEntry: () -> Unit
) {
    Column(modifier = Modifier.fillMaxSize()) {
        // Results count with pass info
        Text(
            text = "Found ${state.candidates.size} places within ${state.radiusKm}km (pass ${state.passNumber} of 3)",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
        )

        // Candidates list
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            items(state.candidates, key = { it.placeId }) { candidate ->
                PlaceCandidateCard(
                    candidate = candidate,
                    isSelected = candidate.placeId == state.selectedPlaceId,
                    onClick = { onSelectCandidate(candidate) }
                )
            }
        }

        // Bottom buttons
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // Confirm button
            Button(
                onClick = onConfirmSelection,
                enabled = state.hasSelection,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Use this place")
            }

            // Expand radius button
            if (state.canExpand) {
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedButton(
                    onClick = onExpandRadius,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    val nextRadius = when (state.radiusKm) {
                        25 -> 50
                        50 -> 100
                        else -> 100
                    }
                    Text("Search wider (${nextRadius}km)")
                }
            }

            // Manual entry button
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(
                onClick = onManualEntry,
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(
                    imageVector = Icons.Default.Edit,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Enter phone manually")
            }
        }
    }
}

@Composable
private fun PlaceCandidateCard(
    candidate: PlaceCandidate,
    isSelected: Boolean,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        ),
        border = if (isSelected) {
            BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
        } else {
            null
        }
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = Icons.Default.Place,
                contentDescription = null,
                tint = if (isSelected) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.size(24.dp)
            )

            Spacer(modifier = Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = candidate.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    color = if (isSelected) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    }
                )

                if (candidate.formattedAddress != null) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = candidate.formattedAddress,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isSelected) {
                            MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f)
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                // Show distance if available
                if (candidate.distanceMeters != null) {
                    Spacer(modifier = Modifier.height(2.dp))
                    val distanceText = if (candidate.distanceMeters >= 1000) {
                        "${candidate.distanceMeters / 1000}km away"
                    } else {
                        "${candidate.distanceMeters}m away"
                    }
                    Text(
                        text = distanceText,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (isSelected) {
                            MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.6f)
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                        }
                    )
                }
            }

            if (isSelected) {
                Spacer(modifier = Modifier.width(8.dp))
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = "Selected",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp)
                )
            }
        }
    }
}

@Composable
private fun NoResultsContent(
    state: PlaceSearchState.NoResults,
    onExpandRadius: () -> Unit,
    onManualEntry: () -> Unit,
    onGoBack: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(32.dp)
        ) {
            Text(
                text = "No places found",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold
            )

            Spacer(modifier = Modifier.height(8.dp))

            val message = state.error ?: "No matching places found within ${state.radiusKm}km (pass ${state.passNumber} of 3)."
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(24.dp))

            if (state.canExpand) {
                Button(
                    onClick = onExpandRadius,
                    shape = RoundedCornerShape(12.dp)
                ) {
                    val nextRadius = when (state.radiusKm) {
                        25 -> 50
                        50 -> 100
                        else -> 100
                    }
                    Text("Search wider (${nextRadius}km)")
                }

                Spacer(modifier = Modifier.height(12.dp))
            }

            OutlinedButton(
                onClick = onManualEntry,
                shape = RoundedCornerShape(12.dp)
            ) {
                Icon(
                    imageVector = Icons.Default.Edit,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Enter phone manually")
            }

            Spacer(modifier = Modifier.height(12.dp))

            TextButton(onClick = onGoBack) {
                Text("Back to chat")
            }
        }
    }
}

@Composable
private fun ErrorContent(
    message: String,
    onRetry: () -> Unit,
    onManualEntry: () -> Unit,
    onBackToResults: () -> Unit,
    onGoBack: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(32.dp)
        ) {
            Text(
                text = "Something went wrong",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(24.dp))

            Button(
                onClick = onRetry,
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Retry")
            }

            Spacer(modifier = Modifier.height(12.dp))

            OutlinedButton(
                onClick = onManualEntry,
                shape = RoundedCornerShape(12.dp)
            ) {
                Icon(
                    imageVector = Icons.Default.Edit,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text("Enter phone manually")
            }

            Spacer(modifier = Modifier.height(12.dp))

            TextButton(onClick = onBackToResults) {
                Text("Back to results")
            }

            Spacer(modifier = Modifier.height(8.dp))

            TextButton(onClick = onGoBack) {
                Text("Back to chat")
            }
        }
    }
}

@Composable
private fun ResolvingContent(placeName: String) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "Fetching details for $placeName...",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
private fun ResolvedContent(
    state: PlaceSearchState.Resolved,
    onContinue: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(32.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Check,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(64.dp)
            )

            Spacer(modifier = Modifier.height(16.dp))

            Text(
                text = state.businessName,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center
            )

            if (state.formattedAddress != null) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = state.formattedAddress,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "Phone: ${state.phoneE164}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Medium
            )

            Spacer(modifier = Modifier.height(32.dp))

            Button(
                onClick = onContinue,
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
}

@Composable
private fun ManualEntryDialog(
    initialName: String,
    error: String?,
    onDismiss: () -> Unit,
    onSubmit: (name: String, phone: String) -> Boolean
) {
    var businessName by remember { mutableStateOf(initialName) }
    var phoneNumber by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Enter phone manually",
                fontWeight = FontWeight.SemiBold
            )
        },
        text = {
            Column {
                Text(
                    text = "Enter the business details to proceed with the call.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                Spacer(modifier = Modifier.height(16.dp))

                OutlinedTextField(
                    value = businessName,
                    onValueChange = { businessName = it },
                    label = { Text("Business name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(
                        imeAction = ImeAction.Next
                    )
                )

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = phoneNumber,
                    onValueChange = { phoneNumber = it },
                    label = { Text("Phone number") },
                    placeholder = { Text("e.g., 07 3182 4583") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Phone,
                        imeAction = ImeAction.Done
                    ),
                    keyboardActions = KeyboardActions(
                        onDone = { onSubmit(businessName, phoneNumber) }
                    ),
                    isError = error != null,
                    supportingText = if (error != null) {
                        { Text(error, color = MaterialTheme.colorScheme.error) }
                    } else {
                        { Text("Australian format (e.g., 07 3182 4583 or +61 7 3182 4583)") }
                    }
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onSubmit(businessName, phoneNumber) },
                enabled = businessName.isNotBlank() && phoneNumber.isNotBlank()
            ) {
                Text("Submit")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}
