# V2 Engine Deployment Guide

This document covers the deployment and rollout of the V2 conversation engine.

> **IMPORTANT**: For production rollout, use `ROLLOUT_LOG.md` to track progress.
> For smoke testing, use `SmokeRun.md` for curl commands and artifacts checklist.

---

## FAST ROLLBACK (Read This First)

If something goes wrong in production, rollback immediately:

```bash
# 1. Set kill switch ON
export CONVERSATION_ENGINE_KILL_SWITCH=true

# 2. Restart/reload service
# (your platform-specific restart command)

# 3. Verify in logs:
#    [STARTUP] Kill switch active: True
#    [KILL_SWITCH] Routing /v2 request to v1
```

**Rollback triggers**:
- Repeated fallbacks across many conversations
- Twilio calls failing or looping
- Missing required slots reaching /call/brief
- App navigation stuck (COMPLETE never reached)
- `[V2-ANOMALY]` warnings in logs

**After rollback**: Re-run one smoke test (STOCK_CHECKER) to confirm recovery.

---

## Architecture Overview

The V2 engine replaces the LLM-driven flow control with a deterministic approach:

| Component | V1 (Legacy) | V2 (New) |
|-----------|-------------|----------|
| Slot Definitions | Hardcoded in `openai_service.py` | `AgentSpec` registry in `agents/specs.py` |
| Flow Control | LLM decides next action | Deterministic planner in `engine/planner.py` |
| LLM Usage | Every turn | Only for slot extraction when needed |
| Phone Routing | Per-agent if/else in client | Generic via `agentMeta.phoneSource` |
| Quick Replies | Hardcoded per agent | Universal via `quickReplies` array |

### Key Benefits

1. **Predictable Flow**: Questions always asked in defined order
2. **Lower Cost**: LLM only called for extraction, not flow decisions
3. **Easier Testing**: Deterministic behavior = deterministic tests
4. **Simpler Client**: Generic handling via `agentMeta`, no per-agent logic

---

## Environment Variables

### Required

```bash
OPENAI_API_KEY=sk-...          # Required for slot extraction
GOOGLE_PLACES_API_KEY=...      # Required for place search
```

### V2 Engine Configuration

```bash
# Engine version (default: v2)
CONVERSATION_ENGINE_VERSION=v2

# Kill switch for instant rollback (default: false)
CONVERSATION_ENGINE_KILL_SWITCH=false
```

### Twilio (Optional)

```bash
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
WEBHOOK_BASE_URL=https://your-server.com
```

---

## Rollout Checklist

### Pre-Deployment

- [ ] Run all backend tests: `python3 -m pytest tests/ -v`
- [ ] Run Android unit tests: `./gradlew test`
- [ ] Complete SmokeRun.md scenarios locally
- [ ] Verify startup log shows `[STARTUP] Conversation engine: v2`

### Staging Deployment

1. Deploy with `CONVERSATION_ENGINE_VERSION=v2`
2. Verify startup log:
   ```
   [STARTUP] Conversation engine: v2
   [STARTUP] Kill switch active: False
   ```
3. Run smoke tests against staging
4. Monitor for `[V2-SUMMARY]` logs
5. Check for `[V2-ANOMALY]` warnings

### Production Deployment

1. Deploy with `CONVERSATION_ENGINE_KILL_SWITCH=false` (default)
2. Monitor first 100 requests for anomalies
3. Check metrics summary log: `[V2-METRICS] total=100 ...`
4. If issues: Set `CONVERSATION_ENGINE_KILL_SWITCH=true` to rollback

---

## Kill Switch

The kill switch provides instant rollback without code deployment:

```bash
# Enable kill switch (routes all /v2 traffic to v1)
CONVERSATION_ENGINE_KILL_SWITCH=true

# Disable kill switch (normal v2 operation)
CONVERSATION_ENGINE_KILL_SWITCH=false
```

When enabled:
- All `/v2/conversation/next` requests are routed to the v1 endpoint
- Log shows: `[KILL_SWITCH] Routing /v2 request to v1 for conversationId=...`
- No code changes required, just environment variable

---

## Monitoring

### Structured Logs

Every V2 request logs a summary line:

```
[V2-SUMMARY] id=conv-123 agent=SICK_CALLER action=ASK_QUESTION question=employer_phone slots_filled=1 ai_used=false
```

Fields:
- `id`: Conversation ID
- `agent`: Agent type handling the request
- `action`: Planner decision (ASK_QUESTION, CONFIRM, COMPLETE, FIND_PLACE)
- `question`: Slot being asked (or "none")
- `slots_filled`: Total slots collected
- `ai_used`: Whether LLM was called

### Metrics Summary

Every 100 requests, a metrics summary is logged:

```
[V2-METRICS] total=100 llm_rate=15.0% fallback_rate=0.0% idempotency_hits=5 actions={CONFIRM=10, COMPLETE=10, FIND_PLACE=5, ASK_QUESTION=75}
```

### Anomaly Detection

Consecutive fallback usage triggers warnings:

```
[V2-ANOMALY] consecutive_fallbacks=3 (threshold=3, max_seen=3)
```

---

## API Changes

### New Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `engineVersion` | string | "v2" for new engine |
| `agentMeta` | object | Phone routing metadata |
| `quickReplies` | array | Universal UI chips |
| `debugPayload` | object | Debug info when `debug=true` |

### agentMeta Structure

```json
{
  "phoneSource": "PLACE" | "DIRECT_SLOT",
  "directPhoneSlot": "employer_phone" | null,
  "title": "Call in Sick",
  "description": "Notify your employer"
}
```

### quickReplies Structure

```json
[
  {"label": "Sick", "value": "SICK"},
  {"label": "Personal", "value": "PERSONAL"}
]
```

---

## Troubleshooting

### Slots Being Lost

1. Check Android `TaskSessionViewModel.updateSlots()` uses merge
2. Verify backend returns full `extractedData` with merged slots
3. Look for `[V2-SUMMARY]` log showing `slots_filled` count

### Wrong Question Order

1. Check `AgentSpec.slots` order in `agents/specs.py`
2. Verify `get_missing_required_slots()` returns correct order

### High LLM Usage

Expected LLM rate is ~15-20% (only for free-form text extraction).

If higher:
1. Check CHOICE slots have `quick_replies` defined
2. Verify `currentQuestionSlotName` is sent from client
3. Check extraction short-circuit logic in `engine/extract.py`

### Kill Switch Not Working

1. Verify env var is set: `echo $CONVERSATION_ENGINE_KILL_SWITCH`
2. Check startup log shows: `[STARTUP] Kill switch active: True`
3. Restart server after changing env var

---

## Rollback Procedure

### Immediate (Kill Switch) - Use This First

**Step 1**: Set kill switch ON
```bash
export CONVERSATION_ENGINE_KILL_SWITCH=true
```

**Step 2**: Restart/reload service
```bash
# Platform-specific restart command
```

**Step 3**: Verify in logs
```
[STARTUP] Kill switch active: True
```

**Step 4**: Test one request
```bash
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{"conversationId":"rollback-verify","agentType":"STOCK_CHECKER","userMessage":"test","slots":{}}'
```
Look for log line: `[KILL_SWITCH] Routing /v2 request to v1`

**Step 5**: Re-run one smoke test to confirm recovery

### Rollback Triggers

Rollback immediately if you see:
- `[V2-ANOMALY]` warnings in logs
- Repeated fallbacks across conversations
- Twilio calls failing or looping
- Missing required slots reaching /call/brief
- App navigation stuck (COMPLETE never reached)
- `fallback_rate` > 5% in `[V2-METRICS]`

### Full Rollback (If Kill Switch Insufficient)

1. Deploy previous version with `/conversation/next` as primary
2. Update Android client to use `/conversation/next`
3. Remove v2 environment variables

### Post-Rollback

1. Investigate root cause using `[V2-SUMMARY]` logs
2. Check `[V2-METRICS]` for patterns before failure
3. Document in `ROLLOUT_LOG.md`

---

## Test Coverage

### Backend (233+ tests)

- `test_golden_paths.py`: 18 end-to-end flow tests
- `test_deterministic_script.py`: 27 DETERMINISTIC_SCRIPT tests
- `test_kill_switch.py`: 8 kill switch tests
- `test_planner.py`: Deterministic planner tests
- `test_extract.py`: Slot extraction tests
- `test_specs.py`: AgentSpec registry tests

### Android (46+ tests)

- `TaskSessionViewModelTest.kt`: 11 slot merge tests
- `ChatUiStateTest.kt`: UI state tests
- `ConversationModelsTest.kt`: quickReplies/agentMeta tests

Run all tests:

```bash
# Backend
cd backend_v2 && python3 -m pytest tests/ -v

# Android
./gradlew test
```

---

## Files Changed (Summary)

### New Files

- `backend_v2/agents/specs.py` - AgentSpec registry
- `backend_v2/engine/planner.py` - Deterministic planner
- `backend_v2/engine/extract.py` - Slot extraction
- `backend_v2/app/conversation_v2.py` - V2 endpoint handler
- `SmokeRun.md` - Smoke test protocol
- `DEPLOYMENT_V2.md` - This file

### Modified Files

- `backend_v2/app/main.py` - Added `/v2/conversation/next`, kill switch
- `backend_v2/app/models.py` - Added `agentMeta`, `quickReplies`, `debugPayload`
- `app/.../TaskSessionViewModel.kt` - Slot merge fix
- `app/.../ChatViewModel.kt` - V2 endpoint integration

### Deprecated (Preserved for Rollback)

- `backend_v2/app/openai_service.py` - V1 LLM-driven flow
- `/conversation/next` endpoint - V1 endpoint
