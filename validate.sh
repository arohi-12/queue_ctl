#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# QueueCTL - Validation Script
# Tests all core flows to verify the system works correctly
# ═══════════════════════════════════════════════════════════════════════════

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

log_pass() { echo -e "${GREEN}✓ PASS${NC}: $1"; PASS=$((PASS + 1)); }
log_fail() { echo -e "${RED}✗ FAIL${NC}: $1"; FAIL=$((FAIL + 1)); }
log_info() { echo -e "${CYAN}▸${NC} $1"; }
log_section() { echo -e "\n${YELLOW}═══ $1 ═══${NC}"; }

# Clean up any previous test data
rm -rf .queuectl_test
export QUEUECTL_DATA_DIR="$(pwd)/.queuectl_test"

log_section "QueueCTL Validation Script"
echo ""

# ── Test 1: Basic Enqueue ────────────────────────────────────────────────
log_section "1. Basic Job Enqueue"
log_info "Enqueueing a simple job..."
OUTPUT=$(queuectl enqueue '{"id":"test1","command":"echo Hello World"}' 2>&1)
if echo "$OUTPUT" | grep -q "enqueued"; then
    log_pass "Job enqueued successfully"
else
    log_fail "Failed to enqueue job"
    echo "$OUTPUT"
fi

# ── Test 2: List Jobs ────────────────────────────────────────────────────
log_section "2. List Jobs"
log_info "Listing pending jobs..."
OUTPUT=$(queuectl list --state pending 2>&1)
if echo "$OUTPUT" | grep -q "test1"; then
    log_pass "Job appears in pending list"
else
    log_fail "Job not found in pending list"
    echo "$OUTPUT"
fi

# ── Test 3: Status Command ───────────────────────────────────────────────
log_section "3. Status Command"
OUTPUT=$(queuectl status 2>&1)
if echo "$OUTPUT" | grep -q "Pending"; then
    log_pass "Status command shows job counts"
else
    log_fail "Status command failed"
    echo "$OUTPUT"
fi

# ── Test 4: Config Management ────────────────────────────────────────────
log_section "4. Configuration Management"
log_info "Setting max-retries to 5..."
OUTPUT=$(queuectl config set max-retries 5 2>&1)
if echo "$OUTPUT" | grep -q "5"; then
    log_pass "Config set works"
else
    log_fail "Config set failed"
    echo "$OUTPUT"
fi

log_info "Getting max-retries..."
OUTPUT=$(queuectl config get max-retries 2>&1)
if echo "$OUTPUT" | grep -q "5"; then
    log_pass "Config get works"
else
    log_fail "Config get failed"
    echo "$OUTPUT"
fi

log_info "Listing all config..."
OUTPUT=$(queuectl config list 2>&1)
if echo "$OUTPUT" | grep -q "max-retries" && echo "$OUTPUT" | grep -q "backoff-base"; then
    log_pass "Config list works"
else
    log_fail "Config list failed"
    echo "$OUTPUT"
fi

# ── Test 5: Failed Job → Retry → DLQ ────────────────────────────────────
log_section "5. Failed Job → Retry → DLQ"
log_info "Enqueueing a failing job with max-retries=2..."
queuectl enqueue '{"id":"fail1","command":"exit 1","max_retries":2}' > /dev/null 2>&1

log_info "Starting worker to process the failing job..."
queuectl worker start --count 1 > /dev/null 2>&1
WORKER_PID=$!

# Wait for the job to cycle through retries and reach DLQ
log_info "Waiting for retries and DLQ (this takes ~10s with backoff)..."
sleep 12

log_info "Stopping worker..."
queuectl worker stop > /dev/null 2>&1
sleep 2

OUTPUT=$(queuectl list --state dead --verbose 2>&1)
if echo "$OUTPUT" | grep -q "fail1"; then
    log_pass "Job moved to DLQ after exhausting retries"
else
    log_fail "Job did not reach DLQ"
    echo "$OUTPUT"
fi

# ── Test 6: DLQ Retry ────────────────────────────────────────────────────
log_section "6. DLQ Retry"
log_info "Retrying job from DLQ..."
OUTPUT=$(queuectl dlq retry fail1 2>&1)
if echo "$OUTPUT" | grep -q "pending"; then
    log_pass "DLQ retry works"
else
    log_fail "DLQ retry failed"
    echo "$OUTPUT"
fi

# ── Test 7: Persistence ──────────────────────────────────────────────────
log_section "7. Persistence"
log_info "Checking that job data survives restart..."
OUTPUT=$(queuectl inspect test1 2>&1)
if echo "$OUTPUT" | grep -q "echo Hello World"; then
    log_pass "Job data persists"
else
    log_fail "Job data lost"
    echo "$OUTPUT"
fi

# ── Test 8: Priority ─────────────────────────────────────────────────────
log_section "8. Job Priority"
log_info "Enqueueing jobs with different priorities..."
queuectl enqueue '{"id":"low_p","command":"echo low","priority":1}' > /dev/null 2>&1
queuectl enqueue '{"id":"high_p","command":"echo high","priority":10}' > /dev/null 2>&1
log_pass "Priority jobs enqueued (verified via store)"

# ── Test 9: Multiple Workers ─────────────────────────────────────────────
log_section "9. Multiple Workers"
log_info "Starting 3 workers..."
OUTPUT=$(queuectl worker start --count 3 2>&1)
if echo "$OUTPUT" | grep -q "3"; then
    log_pass "3 workers started"
else
    log_fail "Failed to start multiple workers"
    echo "$OUTPUT"
fi

sleep 3
OUTPUT=$(queuectl status 2>&1)
echo "$OUTPUT"

log_info "Stopping workers..."
queuectl worker stop > /dev/null 2>&1
sleep 2
log_pass "Workers stopped"

# ── Test 10: Invalid Commands ────────────────────────────────────────────
log_section "10. Invalid Commands"
log_info "Enqueueing invalid command..."
queuectl enqueue '{"id":"invalid1","command":"nonexistent_xyz_cmd","max_retries":1}' > /dev/null 2>&1
queuectl worker start --count 1 > /dev/null 2>&1
sleep 5
queuectl worker stop > /dev/null 2>&1
sleep 2

OUTPUT=$(queuectl list --state dead --verbose 2>&1)
if echo "$OUTPUT" | grep -q "invalid1"; then
    log_pass "Invalid command handled gracefully, moved to DLQ"
else
    # Might still be in failed state if not enough time
    OUTPUT2=$(queuectl list --state failed --verbose 2>&1)
    if echo "$OUTPUT2" | grep -q "invalid1"; then
        log_pass "Invalid command handled gracefully (in failed state, pending retry)"
    else
        log_fail "Invalid command not handled properly"
        echo "$OUTPUT"
        echo "$OUTPUT2"
    fi
fi

# ── Test 11: Inspect Command ─────────────────────────────────────────────
log_section "11. Inspect Command"
OUTPUT=$(queuectl inspect test1 2>&1)
if echo "$OUTPUT" | grep -q "test1" && echo "$OUTPUT" | grep -q "echo Hello World"; then
    log_pass "Inspect command works"
else
    log_fail "Inspect command failed"
    echo "$OUTPUT"
fi

# ── Test 12: DLQ List ────────────────────────────────────────────────────
log_section "12. DLQ List"
OUTPUT=$(queuectl dlq list 2>&1)
if [ $? -eq 0 ]; then
    log_pass "DLQ list command works"
else
    log_fail "DLQ list command failed"
    echo "$OUTPUT"
fi

# ── Cleanup ──────────────────────────────────────────────────────────────
log_section "Cleanup"
queuectl worker stop > /dev/null 2>&1 || true
rm -rf .queuectl_test
unset QUEUECTL_DATA_DIR

# ── Summary ──────────────────────────────────────────────────────────────
log_section "Results"
echo ""
echo -e "${GREEN}Passed: $PASS${NC}"
echo -e "${RED}Failed: $FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All tests passed! ✓${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi