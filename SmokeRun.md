# Smoke Run Protocol - V2 Engine Verification

This document provides a step-by-step smoke test protocol to verify the V2 conversation engine is working correctly before production rollout.

---

## Preconditions

Before running smoke tests, ensure:

1. **Environment Variables**
   ```bash
   export CONVERSATION_ENGINE_VERSION=v2
   export OPENAI_API_KEY=<your-key>
   # Optional: TWILIO_TEST_NUMBER for call verification
   ```

2. **Server Running**
   ```bash
   cd backend_v2
   uvicorn app.main:app --reload --port 8000
   ```

3. **Verify Startup Log**
   Look for: `[STARTUP] Conversation engine: v2`

---

## Scenario 1: STOCK_CHECKER (PLACE phone source)

**Purpose**: Verify place-based agent flow with LLM extraction

### Exact User Inputs

| Turn | User Input | Expected Slot | Expected nextAction |
|------|-----------|---------------|---------------------|
| 1 | "I need to check if JB Hi-Fi has the Sony WH-1000XM5 headphones" | `product_name` | ASK_QUESTION |
| 2 | "3" | `quantity` | FIND_PLACE |
| 3 | *(select place from UI)* | `place_id`, `place_phone` | CONFIRM |
| 4 | *(tap Confirm)* | - | COMPLETE |

### Expected Slot Order
1. `product_name` → "Sony WH-1000XM5 headphones"
2. `quantity` → "3"
3. `place_id` → (from place search)
4. `place_phone` → (from place search)

### Curl Harness

```bash
# Turn 1: Initial message with product
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-stock-001",
    "agentType": "STOCK_CHECKER",
    "userMessage": "I need to check if JB Hi-Fi has the Sony WH-1000XM5 headphones",
    "slots": {},
    "debug": true
  }' | jq .

# Turn 2: Quantity
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-stock-001",
    "agentType": "STOCK_CHECKER",
    "userMessage": "3",
    "currentQuestionSlotName": "quantity",
    "slots": {"product_name": "Sony WH-1000XM5 headphones"},
    "debug": true
  }' | jq .

# After place selection - Confirm
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-stock-001",
    "agentType": "STOCK_CHECKER",
    "userMessage": "",
    "clientAction": "CONFIRM",
    "slots": {
      "product_name": "Sony WH-1000XM5 headphones",
      "quantity": "3",
      "place_id": "ChIJ...",
      "place_phone": "+61299998888"
    }
  }' | jq .
```

---

## Scenario 2: SICK_CALLER (DIRECT_SLOT phone source, DETERMINISTIC_SCRIPT)

**Purpose**: Verify direct phone slot with deterministic script flow

### Exact User Inputs

| Turn | User Input | Expected Slot | Expected nextAction |
|------|-----------|---------------|---------------------|
| 1 | "I need to call in sick to Bunnings" | `employer_name` | ASK_QUESTION |
| 2 | "+61412345678" | `employer_phone` | ASK_QUESTION |
| 3 | "Richard" | `caller_name` | ASK_QUESTION |
| 4 | "tomorrow" | `shift_date` | ASK_QUESTION |
| 5 | "9am" | `shift_start_time` | ASK_QUESTION |
| 6 | *(tap "Sick" chip)* | `reason_category` | CONFIRM |
| 7 | *(tap Confirm)* | - | COMPLETE |

### Expected Slot Order
1. `employer_name` → "Bunnings"
2. `employer_phone` → "+61412345678"
3. `caller_name` → "Richard"
4. `shift_date` → "tomorrow"
5. `shift_start_time` → "9am"
6. `reason_category` → "SICK"

### Curl Harness

```bash
# Turn 1: Employer name
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "I need to call in sick to Bunnings",
    "slots": {},
    "debug": true
  }' | jq .

# Turn 2: Phone number
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "+61412345678",
    "currentQuestionSlotName": "employer_phone",
    "slots": {"employer_name": "Bunnings"},
    "debug": true
  }' | jq .

# Turn 3: Caller name
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "Richard",
    "currentQuestionSlotName": "caller_name",
    "slots": {"employer_name": "Bunnings", "employer_phone": "+61412345678"},
    "debug": true
  }' | jq .

# Turn 4: Shift date
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "tomorrow",
    "currentQuestionSlotName": "shift_date",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard"
    },
    "debug": true
  }' | jq .

# Turn 5: Shift time
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "9am",
    "currentQuestionSlotName": "shift_start_time",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow"
    },
    "debug": true
  }' | jq .

# Turn 6: Reason category (choice)
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "SICK",
    "currentQuestionSlotName": "reason_category",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow",
      "shift_start_time": "9am"
    },
    "debug": true
  }' | jq .

# Turn 7: Confirm
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "userMessage": "",
    "clientAction": "CONFIRM",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow",
      "shift_start_time": "9am",
      "reason_category": "SICK"
    }
  }' | jq .
```

---

## Scenario 3: Rejection Flow

**Purpose**: Verify REJECT action loops back to first missing slot

### Curl Harness

```bash
# Complete all slots, then reject
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-reject-001",
    "agentType": "SICK_CALLER",
    "userMessage": "",
    "clientAction": "REJECT",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow",
      "shift_start_time": "9am",
      "reason_category": "SICK"
    },
    "debug": true
  }' | jq .
```

**Expected**: `nextAction` = `ASK_QUESTION`, asking about `employer_name` again

---

## Call Endpoints (Post-Confirmation)

After COMPLETE, test the call flow:

```bash
# Get call brief
curl -X POST http://localhost:8000/call/brief \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow",
      "shift_start_time": "9am",
      "reason_category": "SICK"
    },
    "phoneE164": "+61412345678"
  }' | jq .

# Start call (requires Twilio credentials)
curl -X POST http://localhost:8000/call/start \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "smoke-sick-001",
    "agentType": "SICK_CALLER",
    "slots": {
      "employer_name": "Bunnings",
      "employer_phone": "+61412345678",
      "caller_name": "Richard",
      "shift_date": "tomorrow",
      "shift_start_time": "9am",
      "reason_category": "SICK"
    },
    "phoneE164": "+61412345678"
  }' | jq .

# Check call status
curl "http://localhost:8000/call/status?call_sid=<CALL_SID>" | jq .
```

---

## Required Artifacts Checklist

After completing smoke runs, collect these artifacts:

### Per Scenario

- [ ] **Screenshot**: Confirmation card shown correctly
- [ ] **Screenshot**: All slots visible in confirmation lines
- [ ] **Log Line**: `[V2-SUMMARY]` log showing correct action flow
- [ ] **Response**: `engineVersion: "v2"` in all responses
- [ ] **Response**: `agentMeta` present with correct `phoneSource`

### Debug Payload Verification

When `debug: true`, verify `debugPayload` contains:
- [ ] `planner_action` matches `nextAction`
- [ ] `planner_question_slot` matches `question.field`
- [ ] `extraction_llm_used` is `false` for CHOICE inputs
- [ ] `merged_slots` contains all accumulated slots
- [ ] `missing_required_slots` decreases each turn

### SICK_CALLER Specific

- [ ] **Verify**: `agentMeta.phoneSource` = `"DIRECT_SLOT"`
- [ ] **Verify**: `agentMeta.directPhoneSlot` = `"employer_phone"`
- [ ] **Verify**: DETERMINISTIC_SCRIPT mode in call brief

### STOCK_CHECKER Specific

- [ ] **Verify**: `agentMeta.phoneSource` = `"PLACE"`
- [ ] **Verify**: `agentMeta.directPhoneSlot` = `null`
- [ ] **Verify**: `placeSearchParams` returned on FIND_PLACE

---

## Troubleshooting

### Slots Being Lost

If slots disappear between turns:
1. Check Android `TaskSessionViewModel.updateSlots()` uses merge (not replace)
2. Verify backend returns full `extractedData` with merged slots
3. Check `[V2-SUMMARY]` log for `slots_filled` count

### Wrong Question Order

If questions appear out of order:
1. Check `AgentSpec.slots` order in `backend_v2/agents/specs.py`
2. Verify `get_missing_required_slots()` returns correct order

### LLM Called Unexpectedly

If `aiCallMade: true` when it should be `false`:
1. Check `currentQuestionSlotName` is being sent
2. Verify slot has `quick_replies` for CHOICE type
3. Check extraction short-circuit logic in `extract.py`

---

## Sign-Off

| Scenario | Tester | Date | Pass/Fail |
|----------|--------|------|-----------|
| STOCK_CHECKER | | | |
| SICK_CALLER | | | |
| Rejection Flow | | | |
| Call Brief | | | |
| Call Start | | | |
