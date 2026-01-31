package com.calleroo.app.ui.screens.agentselect

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Inventory
import androidx.compose.material.icons.filled.EventBusy
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.calleroo.app.domain.model.AgentType
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentSelectScreen(
    onAgentSelected: (AgentType, String) -> Unit
) {
    var selectedAgent by remember { mutableStateOf<AgentType?>(null) }

    val agents = listOf(
        AgentTile(
            type = AgentType.STOCK_CHECKER,
            icon = Icons.Default.Inventory,
            title = "Stock Check",
            description = "Check product availability at retailers"
        ),
        AgentTile(
            type = AgentType.RESTAURANT_RESERVATION,
            icon = Icons.Default.Restaurant,
            title = "Book Restaurant",
            description = "Book a table at a restaurant"
        ),
        AgentTile(
            type = AgentType.SICK_CALLER,
            icon = Icons.Default.LocalHospital,
            title = "Call in Sick",
            description = "Notify your workplace you're unwell"
        ),
        AgentTile(
            type = AgentType.CANCEL_APPOINTMENT,
            icon = Icons.Default.EventBusy,
            title = "Cancel Appointment",
            description = "Cancel an existing booking for you"
        )
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "Calleroo",
                        fontWeight = FontWeight.Bold
                    )
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
                .padding(16.dp)
        ) {
            Text(
                text = "What would you like to do?",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Medium
            )

            Spacer(modifier = Modifier.height(24.dp))

            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = PaddingValues(bottom = 80.dp),
                modifier = Modifier.weight(1f)
            ) {
                items(agents) { agent ->
                    AgentTileCard(
                        agent = agent,
                        isSelected = selectedAgent == agent.type,
                        onClick = { selectedAgent = agent.type }
                    )
                }
            }

            Button(
                onClick = {
                    selectedAgent?.let { agentType ->
                        val conversationId = UUID.randomUUID().toString()
                        onAgentSelected(agentType, conversationId)
                    }
                },
                enabled = selectedAgent != null,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
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

private data class AgentTile(
    val type: AgentType,
    val icon: ImageVector,
    val title: String,
    val description: String
)

@Composable
private fun AgentTileCard(
    agent: AgentTile,
    isSelected: Boolean,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface
            }
        ),
        border = if (isSelected) {
            BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
        } else {
            BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
        },
        elevation = CardDefaults.cardElevation(
            defaultElevation = if (isSelected) 4.dp else 1.dp
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = agent.icon,
                contentDescription = null,
                modifier = Modifier.size(40.dp),
                tint = if (isSelected) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                }
            )

            Spacer(modifier = Modifier.width(16.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = agent.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (isSelected) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    }
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = agent.description,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (isSelected) {
                        MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f)
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    }
                )
            }

            if (isSelected) {
                Icon(
                    imageVector = Icons.Default.CheckCircle,
                    contentDescription = "Selected",
                    modifier = Modifier.size(24.dp),
                    tint = MaterialTheme.colorScheme.primary
                )
            }
        }
    }
}
