# V2 Engine Rollout Log

**Rollout Date**: 2026-02-01
**Engineer**: _______________
**Environment**: Australia/Brisbane timezone

---

## 1. Staging Go/No-Go

### 1.1 Deployment Configuration

| Setting | Value |
|---------|-------|
| CONVERSATION_ENGINE_VERSION | v2 |
| CONVERSATION_ENGINE_KILL_SWITCH | false |

### 1.2 Startup Log Verification

- [ ] `[STARTUP] Conversation engine: v2` visible
- [ ] `[STARTUP] Kill switch active: False` visible

**Timestamp**: _______________
**Log snippet**:
```
(paste startup log lines here)
```

### 1.3 Smoke Run Results

#### Scenario 1: STOCK_CHECKER

| Turn | User Input | Expected Slot | Actual Result | Pass? |
|------|-----------|---------------|---------------|-------|
| 1 | "Check if JB Hi-Fi has Sony headphones" | product_name | | |
| 2 | "3" | quantity | | |
| 3 | (place selected) | place_id | | |
| 4 | (CONFIRM) | COMPLETE | | |

**[V2-SUMMARY] line**:
```
(paste final turn summary log)
```

**Artifacts collected**:
- [ ] Screenshot: Confirmation card
- [ ] Response: `engineVersion: "v2"`
- [ ] Response: `agentMeta.phoneSource: "PLACE"`

---

#### Scenario 2: SICK_CALLER

| Turn | User Input | Expected Slot | Actual Result | Pass? |
|------|-----------|---------------|---------------|-------|
| 1 | "Call in sick to Bunnings" | employer_name | | |
| 2 | "+61412345678" | employer_phone | | |
| 3 | "Richard" | caller_name | | |
| 4 | "tomorrow" | shift_date | | |
| 5 | "9am" | shift_start_time | | |
| 6 | "SICK" | reason_category | | |
| 7 | (CONFIRM) | COMPLETE | | |

**[V2-SUMMARY] line**:
```
(paste final turn summary log)
```

**Artifacts collected**:
- [ ] Screenshot: Confirmation card with all 6 slots
- [ ] Response: `agentMeta.phoneSource: "DIRECT_SLOT"`
- [ ] Response: `agentMeta.directPhoneSlot: "employer_phone"`
- [ ] Twilio: Zero OpenAI calls in deterministic flow

---

#### Scenario 3: Rejection Flow

| Action | Expected Result | Actual Result | Pass? |
|--------|----------------|---------------|-------|
| CONFIRM all slots | COMPLETE | | |
| REJECT | ASK_QUESTION (employer_name) | | |

**[V2-SUMMARY] line**:
```
(paste rejection flow summary log)
```

---

### 1.4 Acceptance Criteria Checklist

| Criterion | Pass? | Notes |
|-----------|-------|-------|
| No repeated slot asked twice in a row | | |
| extractedData is cumulative, never loses keys | | |
| CONFIRM card matches slots + templates | | |
| /call/brief matches confirm card intent | | |
| Twilio deterministic flow makes zero OpenAI calls | | |
| /call/status terminates cleanly | | |

**STAGING GO/NO-GO DECISION**: [ ] GO / [ ] NO-GO

**Decision timestamp**: _______________
**Approver**: _______________

---

## 2. Production Rollout

### 2.1 Initial Deployment (Kill Switch ON)

| Setting | Value |
|---------|-------|
| CONVERSATION_ENGINE_VERSION | v2 |
| CONVERSATION_ENGINE_KILL_SWITCH | true |

**Deployment timestamp**: _______________

### 2.2 Boot Log Verification

- [ ] `[STARTUP] Kill switch active: True` visible
- [ ] `[KILL_SWITCH] Routing /v2 request to v1` appears on test request

**Log snippet**:
```
(paste startup log lines here)
```

### 2.3 Kill Switch Flip (OFF)

**Flip timestamp**: _______________

- [ ] `CONVERSATION_ENGINE_KILL_SWITCH=false` set
- [ ] Service restarted/reloaded
- [ ] `[STARTUP] Kill switch active: False` confirmed

### 2.4 Production Smoke Runs

#### Scenario 1: STOCK_CHECKER

| Metric | Value |
|--------|-------|
| Timestamp | |
| Result | PASS / FAIL |
| [V2-SUMMARY] line | |

#### Scenario 2: SICK_CALLER

| Metric | Value |
|--------|-------|
| Timestamp | |
| Result | PASS / FAIL |
| [V2-SUMMARY] line | |

#### Scenario 3: Rejection Flow

| Metric | Value |
|--------|-------|
| Timestamp | |
| Result | PASS / FAIL |

### 2.5 15-Minute Watch Period

**Watch start**: _______________
**Watch end**: _______________

| Metric | Observed Value | Threshold | Status |
|--------|---------------|-----------|--------|
| [V2-ANOMALY] count | | 0 | |
| llm_rate % | | <25% for SICK_CALLER | |
| fallback_rate % | | <5% | |
| idempotency_hits | | Normal | |

**Anomalies observed**:
```
(list any anomalies and actions taken)
```

---

## 3. Rollback Events (if any)

### Rollback #1

| Field | Value |
|-------|-------|
| Trigger reason | |
| Timestamp | |
| Kill switch set to | true |
| Recovery confirmed | YES / NO |
| Time to recovery | |

**Actions taken**:
```
(describe what happened and resolution)
```

---

## 4. Post-Rollout Status

### 24-Hour Check

**Timestamp**: _______________

| Metric | Value | Status |
|--------|-------|--------|
| Total v2 requests | | |
| llm_rate % | | |
| fallback_rate % | | |
| Errors/anomalies | | |

### 48-Hour Check

**Timestamp**: _______________

| Metric | Value | Status |
|--------|-------|--------|
| Total v2 requests | | |
| llm_rate % | | |
| fallback_rate % | | |
| Errors/anomalies | | |

**48-Hour Stability Confirmed**: [ ] YES / [ ] NO

---

## 5. Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Engineer | | | |
| Reviewer | | | |

---

## Appendix: Quick Reference

### Fast Rollback Command

```bash
# Set kill switch ON
export CONVERSATION_ENGINE_KILL_SWITCH=true

# Restart service
# (platform-specific command here)

# Verify rollback
curl -X POST http://localhost:8000/v2/conversation/next \
  -H "Content-Type: application/json" \
  -d '{"conversationId":"rollback-test","agentType":"STOCK_CHECKER","userMessage":"test","slots":{}}' \
  | grep -o '"engineVersion":"[^"]*"'
# Should NOT show v2 if kill switch working (v1 doesn't have engineVersion)
```

### Key Log Patterns to Watch

```bash
# Startup verification
grep -E "\[STARTUP\]" app.log

# Kill switch routing
grep -E "\[KILL_SWITCH\]" app.log

# V2 request summaries
grep -E "\[V2-SUMMARY\]" app.log

# Anomaly detection
grep -E "\[V2-ANOMALY\]" app.log

# Metrics summaries
grep -E "\[V2-METRICS\]" app.log
```
