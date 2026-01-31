# Regression Checklist

This checklist verifies the v2 architecture with unified OpenAI-driven conversation loop and Place Search.

---

## Step 1 - Conversation Flow Baseline

## Pre-requisites

- [ ] Backend running: `cd backend_v2 && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- [ ] OpenAI API key configured in `backend_v2/.env`
- [ ] Android app built and running on emulator (uses 10.0.2.2:8000)

---

## Stock Checker Flow

### Initial Setup
- [ ] Launch app - AgentSelectScreen appears
- [ ] "Stock Check" tile is visible
- [ ] "Book Restaurant" tile is visible
- [ ] Continue button is disabled when no tile selected

### Agent Selection
- [ ] Tap "Stock Check" tile - tile becomes highlighted
- [ ] Continue button becomes enabled
- [ ] Tap Continue - navigates to UnifiedChatScreen
- [ ] Top bar shows "Stock Check"

### Conversation Flow
- [ ] Assistant sends initial greeting asking for retailer
- [ ] User types retailer name (e.g., "JB Hi-Fi") and sends
- [ ] Assistant extracts retailer and asks for store location
- [ ] User provides location (e.g., "Richmond")
- [ ] Assistant asks for product name
- [ ] User provides product (e.g., "Sony headphones")
- [ ] Assistant may ask for brand/model/variant (optional fields)
- [ ] User can say "skip" for optional fields
- [ ] **CRITICAL**: Skipped fields are NOT re-asked
- [ ] Assistant asks for quantity
- [ ] User provides quantity

### Confirmation
- [ ] When all required info collected, backend returns CONFIRM
- [ ] Confirmation card appears with:
  - [ ] Title: "Stock Check Request"
  - [ ] Lines listing: Retailer, Location, Product, etc.
  - [ ] "Yes, that's right" button
  - [ ] "Not quite" button

### Confirm - Accept
- [ ] Tap "Yes, that's right"
- [ ] Backend returns COMPLETE
- [ ] Assistant shows completion message
- [ ] "Continue" button appears
- [ ] Tap Continue - logs "NEXT_SCREEN_NOT_IMPLEMENTED"

### Confirm - Reject
- [ ] Tap "Not quite"
- [ ] Assistant asks what needs to be changed
- [ ] User can provide correction
- [ ] Flow continues appropriately

---

## Restaurant Reservation Flow

### Agent Selection
- [ ] From AgentSelectScreen, tap "Book Restaurant" tile
- [ ] Continue -> navigates to UnifiedChatScreen
- [ ] Top bar shows "Book Restaurant"

### Conversation Flow
- [ ] Assistant sends initial greeting asking for restaurant
- [ ] User provides restaurant name (e.g., "The Italian Place")
- [ ] Assistant asks for suburb/area
- [ ] User provides location (e.g., "South Yarra")
- [ ] Assistant asks for party size (may show choice chips)
- [ ] **Choice chips render ONLY when backend sends them**
- [ ] User selects party size
- [ ] Assistant asks for date
- [ ] User provides date
- [ ] Assistant asks for time
- [ ] User provides time
- [ ] Assistant may ask about sharing contact (boolean, optional)
- [ ] User can skip

### Confirmation
- [ ] When all required info collected, backend returns CONFIRM
- [ ] Confirmation card appears with:
  - [ ] Title: "Reservation Details"
  - [ ] Lines: Restaurant, Location, Party size, Date, Time
  - [ ] Confirm/Reject buttons

### Complete
- [ ] Tap confirm -> backend returns COMPLETE
- [ ] Assistant shows completion message
- [ ] Continue button appears

---

## Critical Behavioral Checks

### Backend Authority
- [ ] **Android NEVER decides question order** - all questions come from backend
- [ ] **Android NEVER generates choice chips locally** - only renders what backend sends
- [ ] **aiCallMade is always true** in all responses
- [ ] **aiModel field is populated** in all responses

### No Repeated Questions
- [ ] If user provides info in initial message, backend doesn't re-ask
- [ ] If user says "skip", backend moves on and doesn't re-ask
- [ ] If user declines a field, backend doesn't loop back to it

### Error Handling
- [ ] If backend is down, error snackbar appears
- [ ] If network timeout, error snackbar appears
- [ ] App doesn't crash on network errors

### Debug Guard
- [ ] In debug builds, UnifiedConversationGuard is active
- [ ] If any local question logic were invoked, app would crash
- [ ] Guard validates aiCallMade == true on every response

---

## Backend Tests

Run from `backend_v2/` directory:

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v
```

### Test Cases
- [ ] `test_stock_checker_initial_turn` - passes
- [ ] `test_restaurant_reservation_initial_turn` - passes
- [ ] `test_stock_checker_with_user_message` - passes
- [ ] `test_restaurant_reservation_with_user_message` - passes
- [ ] `test_confirm_action_has_confirmation_card` - passes
- [ ] `test_health_check` - passes

---

## Architecture Compliance

### Hard Rules Verification
- [ ] Android client does NOT decide questions, slots, flow order
- [ ] Backend (OpenAI) is sole authority for all conversation decisions
- [ ] Backend calls OpenAI on EVERY turn (no caching)
- [ ] Debug builds have runtime guard that would crash on local logic
- [ ] Step 1 does NOT implement Places/Twilio/Summary screen

### Code Structure
- [ ] Backend in `backend_v2/` folder (clean, separate from any legacy)
- [ ] Android screens in `com.calleroo.app.ui.screens`
- [ ] No legacy screens reused
- [ ] No old logic ported

---

## Sign-off

| Tester | Date | Pass/Fail | Notes |
|--------|------|-----------|-------|
|        |      |           |       |

---

## Known Limitations (Step 1)

1. **No Google Places lookup** - only collects restaurant/retailer names
2. **No Twilio integration** - no actual calls made
3. **No Summary screen** - "Continue" just logs placeholder
4. **No persistence** - conversation lost on app restart
5. **No offline support** - requires network connection

---

# Step 2 - Place Search Screen

## Pre-requisites

- [ ] Step 1 checks pass
- [ ] Google Places API key configured in `backend_v2/.env` as `GOOGLE_PLACES_API_KEY`
- [ ] Backend shows "Google Places service initialized" on startup

---

## Stock Checker → Place Search Flow

### Trigger FIND_PLACE
- [ ] Complete Stock Checker flow to confirmation
- [ ] Tap "Yes" to confirm
- [ ] Backend returns `nextAction=FIND_PLACE` with `placeSearchParams`
- [ ] App navigates to PlaceSearchScreen
- [ ] PlaceSearchScreen shows "Choose the place to call" title
- [ ] Subtitle shows "Searching for {retailer} near {location}"

### Search Results
- [ ] Loading spinner shown initially
- [ ] Places load with 25km default radius
- [ ] Results count shown: "Found X places within 25km"
- [ ] Each place shows name and address
- [ ] Tap a place card → card becomes selected (highlighted, checkmark)
- [ ] "Use this place" button is disabled until selection made
- [ ] "Search wider" button visible (if radius < 100km)

### Expand Radius
- [ ] Tap "Search wider (50km)" → re-searches with 50km radius
- [ ] Results update with new radius
- [ ] Button changes to "Search wider (100km)"
- [ ] At 100km, "Search wider" button disappears
- [ ] **User must explicitly tap expand** - no automatic expansion

### Resolve Place
- [ ] Select a place and tap "Use this place"
- [ ] Loading: "Fetching details for {placeName}..."
- [ ] Resolved state shows:
  - [ ] Checkmark icon
  - [ ] Business name
  - [ ] Address
  - [ ] Phone number (E.164 format)
- [ ] "Continue" button appears

### Place Without Phone
- [ ] If selected place has no valid phone number:
- [ ] Error state shows "Something went wrong"
- [ ] "Back to results" button allows picking another place
- [ ] User can select a different place

### Navigation
- [ ] Back arrow returns to chat screen
- [ ] Tapping "Continue" on resolved place logs and pops back (Step 2 stop point)

---

## Restaurant Reservation → Place Search Flow

### Trigger FIND_PLACE
- [ ] Complete Restaurant Reservation flow to confirmation
- [ ] Tap "Yes" to confirm
- [ ] Backend returns `nextAction=FIND_PLACE` with `placeSearchParams`
- [ ] App navigates to PlaceSearchScreen
- [ ] Subtitle shows "Searching for {restaurant} near {suburb}"

### Same Place Search UX
- [ ] All place search checks from Stock Checker apply here
- [ ] Search uses restaurant name and area

---

## No Results Handling

- [ ] If search returns 0 results at 25km:
- [ ] "No places found" message shown with pass info (pass 1 of 3)
- [ ] "Search wider (50km)" button available
- [ ] "Enter phone manually" button available
- [ ] Expanding to 50km/100km may find results
- [ ] At 100km with no results, only "Enter phone manually" and "Back to chat" shown

---

## Critical Behavioral Checks (Step 2)

### Deterministic Place Search
- [ ] **Places endpoints do NOT call OpenAI** - deterministic Google Places only
- [ ] `/places/search` uses Text Search API with area geocoding
- [ ] `/places/details` fetches phone number and details
- [ ] Area geocoding provides location bias (NOT GPS)

### No GPS / Location Services
- [ ] App does NOT request location permissions
- [ ] Area is passed from chat (suburb/city name)
- [ ] Geocoding converts area name to lat/lng for search

### Phone Number Validation
- [ ] Only places with valid E.164 phone can proceed
- [ ] Places without phone show error when resolved
- [ ] E.164 format: +61412345678 (Australian example)

### Radius Control
- [ ] Default radius is 25km
- [ ] Radius only increases when user taps expand
- [ ] Valid radii: 25, 50, 100 km only
- [ ] No automatic radius expansion

---

## Backend Place Endpoints Tests

```bash
# Test geocode endpoint
curl -X POST http://localhost:8000/places/geocode \
  -H "Content-Type: application/json" \
  -d '{"area": "Browns Plains", "country": "AU"}'
# Expected: latitude, longitude, formattedAddress

# Test invalid radius (should return 400)
curl -X POST http://localhost:8000/places/search \
  -H "Content-Type: application/json" \
  -d '{"query": "JB Hi-Fi", "area": "Richmond", "radius_km": 30}'
# Expected: HTTP 400

# Test place search with passNumber
curl -X POST http://localhost:8000/places/search \
  -H "Content-Type: application/json" \
  -d '{"query": "JB Hi-Fi", "area": "Richmond VIC", "radius_km": 25}'
# Expected: passNumber=1, radiusKm=25, candidates with distanceMeters

# Test place details
curl -X POST http://localhost:8000/places/details \
  -H "Content-Type: application/json" \
  -d '{"placeId": "ChIJ..."}'
```

- [ ] `/places/geocode` returns valid coordinates for known areas
- [ ] `/places/geocode` returns error (not 500) for unknown areas
- [ ] `/places/search` with invalid radius returns HTTP 400
- [ ] `/places/search` returns passNumber (1, 2, or 3)
- [ ] `/places/search` returns distanceMeters for each candidate
- [ ] `/places/search` returns candidates with placeId, name, address
- [ ] `/places/details` returns phoneE164 for valid places
- [ ] `/places/details` returns `error="NO_PHONE"` for places without phone

---

## Manual Entry Flow

### Trigger Manual Entry from NoResults
- [ ] Complete a flow that leads to NoResults (use an obscure search term)
- [ ] "Enter phone manually" button visible in NoResults state
- [ ] Tap button → Manual entry dialog opens
- [ ] Business name pre-filled with search query
- [ ] Phone number field empty

### Trigger Manual Entry from Error
- [ ] Select a place that has no phone number
- [ ] Error state shows with "Enter phone manually" button
- [ ] Tap button → Manual entry dialog opens

### Trigger Manual Entry from Results
- [ ] "Enter phone manually" link visible at bottom of Results state
- [ ] Tap link → Manual entry dialog opens

### Manual Entry Validation
- [ ] Enter valid AU number (e.g., "07 3182 4583") → accepts
- [ ] Enter valid AU number with country code (e.g., "+61 7 3182 4583") → accepts
- [ ] Enter invalid number (e.g., "12345") → shows error, dialog stays open
- [ ] Enter blank phone → Submit button disabled
- [ ] Enter blank name → shows validation error
- [ ] Valid submission → dialog closes, Resolved state shows

### Manual Entry Result
- [ ] After manual entry, Resolved state shows:
  - [ ] Business name (user-entered)
  - [ ] Phone in E.164 format (e.g., +61731824583)
  - [ ] No address displayed
- [ ] "Continue" button works same as place selection
- [ ] placeId in state is "manual"

---

## Pass Number Display

- [ ] Loading state shows "Within 25km (pass 1 of 3)" for initial search
- [ ] Loading state shows "Within 50km (pass 2 of 3)" after first expand
- [ ] Loading state shows "Within 100km (pass 3 of 3)" after second expand
- [ ] Results state shows "Found X places within Ykm (pass Z of 3)"
- [ ] NoResults state shows "(pass Z of 3)" in message

---

## Sign-off (Step 2)

| Tester | Date | Pass/Fail | Notes |
|--------|------|-----------|-------|
|        |      |           |       |

---

## Known Limitations (Step 2)

1. **No Call/Summary screen** - "Continue" on resolved place logs placeholder
2. **No Twilio integration** - phone number collected but not dialed
3. **No place caching** - searches always hit Google API
4. **Area geocoding only** - no GPS fallback if area lookup fails
5. **Manual entry AU only** - phone validation defaults to Australian format

---

# Step 3 - Call Summary Screen

## Pre-requisites

- [ ] Step 1 and Step 2 checks pass
- [ ] OpenAI API key configured in `backend_v2/.env`
- [ ] Backend shows "Call Brief service initialized" on startup

---

## Stock Checker → Call Summary Flow

### Trigger Navigation to Call Summary
- [ ] Complete Stock Checker flow to confirmation
- [ ] Tap "Yes" to confirm → backend returns FIND_PLACE
- [ ] Navigate to PlaceSearch → select place → tap "Continue"
- [ ] App navigates to CallSummaryScreen
- [ ] Top bar shows "Call Summary"

### Call Brief Loading
- [ ] Loading spinner shown initially ("Loading call brief...")
- [ ] Call brief loads successfully from backend
- [ ] aiCallMade is true in response
- [ ] Screen shows ReadyToReview state

### Business Card
- [ ] Business name displayed
- [ ] Address displayed (if available)
- [ ] Phone number displayed in E.164 format
- [ ] "Edit" button visible for phone number

### Objective Card
- [ ] Objective text displayed (from backend)

### Script Preview Card
- [ ] "Call Script Preview" title shown
- [ ] Script preview text displayed verbatim (no markdown)
- [ ] Script includes OpenAI-generated greeting and request

### Disclosure Toggles
- [ ] "Share my name" toggle visible
- [ ] "Share my phone number" toggle visible
- [ ] Toggle changes trigger debounced refresh (300ms)
- [ ] Script preview updates after toggle change

### Fallback Options (Stock Checker)
- [ ] "Ask for ETA if out of stock" toggle visible
- [ ] "Ask about nearest store" toggle visible
- [ ] Toggle changes trigger debounced refresh

### Pre-call Checklist
- [ ] Checklist items displayed (from backend)
- [ ] Checkboxes start unchecked
- [ ] Tapping checkbox toggles check state
- [ ] "Check all items to enable Start Call" hint shown

### Start Call Button
- [ ] "Start Call" button visible in bottom bar
- [ ] Button disabled when checklist incomplete
- [ ] Button disabled when required fields missing
- [ ] Button enabled when all checklist items checked AND no missing fields
- [ ] Tapping "Start Call" shows toast "Call start not implemented yet"
- [ ] App stays on Call Summary screen (does not crash)

### Edit Phone Number
- [ ] Tap "Edit" on phone → EditingNumber dialog opens
- [ ] Current phone pre-filled in input
- [ ] Valid AU number accepted (e.g., "07 3182 4583")
- [ ] Invalid number shows error, dialog stays open
- [ ] "Confirm" button disabled for invalid input
- [ ] Confirm valid number → call brief refreshes with new phone

### Back Navigation
- [ ] "Back" button returns to PlaceSearch
- [ ] Resolved place cleared on back navigation
- [ ] Can re-select different place

---

## Restaurant Reservation → Call Summary Flow

### Trigger Navigation to Call Summary
- [ ] Complete Restaurant Reservation flow to confirmation
- [ ] Tap "Yes" to confirm → backend returns FIND_PLACE
- [ ] Navigate to PlaceSearch → select place → tap "Continue"
- [ ] App navigates to CallSummaryScreen

### Fallback Options (Restaurant)
- [ ] "Retry if no answer" toggle visible
- [ ] "Retry if busy" toggle visible
- [ ] "Leave voicemail" toggle visible
- [ ] Toggle changes trigger debounced refresh

### Same Call Summary UX
- [ ] All other Call Summary checks from Stock Checker apply here

---

## Required Fields Blocker

### Missing Required Fields
- [ ] If required fields missing, red blocker card shown
- [ ] Card shows "Missing Required Information"
- [ ] Card lists missing field names
- [ ] "Back to Chat" button shown
- [ ] Start Call button disabled

### Navigate to Fix
- [ ] Tap "Back to Chat" → returns to Chat screen
- [ ] Provide missing information → return to Place Search → Call Summary
- [ ] Blocker card no longer shown when fields complete

---

## Critical Behavioral Checks (Step 3)

### Backend Authority
- [ ] **/call/brief ALWAYS calls OpenAI** - aiCallMade=true in all responses
- [ ] **requiredFieldsMissing computed deterministically** - NOT by OpenAI
- [ ] **scriptPreview rendered verbatim** - client does NOT generate
- [ ] **aiModel field populated** in all responses

### Phone Validation
- [ ] Invalid E.164 phone → 400 error from backend
- [ ] Valid E.164 format: +61731824583 (Australian example)
- [ ] Phone validation uses libphonenumber (AU default)

### Debouncing
- [ ] Toggle changes debounced (300ms delay before API call)
- [ ] Multiple rapid toggles don't cause multiple API calls

### Error Handling
- [ ] If /call/brief fails, Error state shown
- [ ] "Retry" button allows re-fetching call brief
- [ ] App doesn't crash on network errors

---

## Backend Call Brief Endpoint Tests

```bash
cd backend_v2

# Test call brief with valid data
curl -X POST http://localhost:8000/call/brief \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "test-123",
    "agentType": "STOCK_CHECKER",
    "place": {
      "placeId": "abc",
      "businessName": "JB Hi-Fi",
      "formattedAddress": "123 Main St",
      "phoneE164": "+61731824583"
    },
    "slots": {"retailer_name": "JB Hi-Fi", "product_name": "Sony Headphones", "store_location": "Richmond"},
    "disclosure": {"nameShare": true, "phoneShare": false},
    "fallbacks": {"askETA": true, "askNearestStore": false},
    "debug": false
  }'
# Expected: aiCallMade=true, scriptPreview non-empty, confirmationChecklist non-empty

# Test invalid phone
curl -X POST http://localhost:8000/call/brief \
  -H "Content-Type: application/json" \
  -d '{"conversationId": "test", "agentType": "STOCK_CHECKER", "place": {"placeId": "a", "businessName": "B", "phoneE164": "invalid"}, "slots": {}, "disclosure": {}, "fallbacks": {}}'
# Expected: HTTP 400 invalid_phone_e164

# Test missing required fields
curl -X POST http://localhost:8000/call/brief \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "test",
    "agentType": "STOCK_CHECKER",
    "place": {"placeId": "a", "businessName": "JB Hi-Fi", "phoneE164": "+61731824583"},
    "slots": {"retailer_name": "JB Hi-Fi"},
    "disclosure": {},
    "fallbacks": {}
  }'
# Expected: requiredFieldsMissing contains ["product_name", "store_location"]

# Test stub call start
curl -X POST http://localhost:8000/call/start/v2 \
  -H "Content-Type: application/json" \
  -d '{"conversationId": "test", "agentType": "STOCK_CHECKER", "placeId": "abc", "phoneE164": "+61731824583", "slots": {}}'
# Expected: {"status": "NOT_IMPLEMENTED", "message": "call_start_not_implemented"}
```

- [ ] `/call/brief` returns aiCallMade=true
- [ ] `/call/brief` returns scriptPreview (non-empty string)
- [ ] `/call/brief` returns confirmationChecklist (array of strings)
- [ ] `/call/brief` with invalid phone returns HTTP 400
- [ ] `/call/brief` returns requiredFieldsMissing for incomplete slots
- [ ] `/call/start/v2` returns NOT_IMPLEMENTED status

---

## Pytest Tests

```bash
cd backend_v2
pytest tests/test_call_brief.py -v
```

- [ ] `test_valid_australian_phone` - passes
- [ ] `test_invalid_no_plus` - passes
- [ ] `test_jb_hifi_is_chain` - passes
- [ ] `test_stock_checker_chain_needs_location` - passes
- [ ] `test_restaurant_complete` - passes
- [ ] `test_invalid_phone_returns_400` - passes
- [ ] `test_valid_request_returns_ai_call_made` - passes
- [ ] `test_returns_not_implemented` - passes

---

## Sign-off (Step 3)

| Tester | Date | Pass/Fail | Notes |
|--------|------|-----------|-------|
|        |      |           |       |

---

## Known Limitations (Step 3)

1. **No actual calling** - /call/start/v2 returns stub "NOT_IMPLEMENTED"
2. **No Twilio integration** - phone number collected but not dialed
3. **No call result screen** - Step 3 stops at Call Summary
4. **Disclosure info not persisted** - settings lost on app restart
5. **No user profile** - name/phone for disclosure must be entered each time
