# Tournament Bugfix: Timers, Brackets, Scores & Security

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four critical bugs — overlapping/unstoppable timers, bracket self-matching, scores exceeding 300, and frontend bracket duplicates with public API data leaks.

**Architecture:** Backend-first fixes in Python (FastAPI), then frontend Timer component fix, then API security hardening. Each task is independently testable. No new files — all edits to existing code.

**Tech Stack:** Python/FastAPI, React, PostgreSQL, WebSocket

---

## Root Cause Analysis

### Bug 1: Timer Overlap & Unstoppable Timers
- `_run_timer()` in `backend/routes/admin.py` doesn't handle `asyncio.CancelledError` — cancelled tasks keep broadcasting ticks
- Sub-round break timer (line 354) creates a task via `asyncio.create_task()` but never stores it in `_timer_task`, so `/api/admin/timer/stop` can't cancel it
- Round break timer (line 419) is `await`ed directly inside `_complete_bracket_round`, blocking the coroutine and making it uncancellable
- Frontend `Timer.jsx` never resets `remaining` to `null` on `timer_end`, leaving stale "00:00" display

### Bug 2: Bracket Self-Matching
- `generate_bracket()` in `backend/bracket.py` doesn't clear existing matches before creating new ones
- If admin calls "Generate Bracket" twice, duplicate matches accumulate in `state._matches`
- `advance_winners()` collects winners from ALL matches for a round (including duplicates), so the same team appears multiple times in the winners list and gets paired with itself

### Bug 3: Scores Exceeding 300
- `ScoreOverride` model in `backend/models.py` has no range validation — admin can set any float value
- During `run_sub_round()` (admin.py:288-293), cumulative team scores sum ALL submissions including those from duplicate matches (Bug 2)
- `determine_match_winner()` (bracket.py:132) overwrites team total_score with just the current match max, conflicting with the cumulative calculation in `run_sub_round`

### Bug 4: Frontend Bracket Duplicates & API Security
- `/api/bracket` returns `list(state.matches.values())` — all matches including duplicates from double generation
- `/api/state` (main.py:47) is publicly accessible with zero auth, exposing full submissions (response_text, reasoning, scores) to competing teams
- `/api/submissions/match/{id}` also exposes response_text and reasoning without auth
- `setup_dummy()` in admin.py has wrong argument order for `state.add_team()` — passes members list as password parameter

---

## File Structure

Files to modify (no new files):

| File | Changes |
|------|---------|
| `backend/routes/admin.py` | Fix timer lifecycle, store all timer tasks, handle cancellation |
| `backend/bracket.py` | Clear existing matches in `generate_bracket()`, deduplicate winners in `advance_winners()` |
| `backend/models.py` | Add score validation to `ScoreOverride`, add `clear_matches()` method |
| `backend/routes/submissions.py` | Redact response_text/reasoning from public endpoints |
| `main.py` | Remove or protect `/api/state`, add limited public state endpoint |
| `frontend/src/components/Timer.jsx` | Reset remaining on timer_end, handle rapid timer transitions |

---

### Task 1: Fix Timer Lifecycle (Backend)

**Files:**
- Modify: `backend/routes/admin.py:17-46` (timer global + `_run_timer`)
- Modify: `backend/routes/admin.py:349-354` (sub-round break timer launch)
- Modify: `backend/routes/admin.py:416-419` (round break timer launch)
- Modify: `backend/routes/admin.py:445-467` (start/stop endpoints)

- [ ] **Step 1: Refactor `_run_timer` to handle cancellation**

Replace the `_run_timer` function and the global `_timer_task` with a version that catches `CancelledError` and broadcasts `timer_end` on cancellation:

```python
_timer_task: asyncio.Task | None = None


async def _cancel_existing_timer():
    """Cancel any running timer task and wait for cleanup."""
    global _timer_task
    if _timer_task and not _timer_task.done():
        _timer_task.cancel()
        try:
            await _timer_task
        except asyncio.CancelledError:
            pass
    _timer_task = None


async def _run_timer(seconds: int, label: str = ""):
    """Broadcast a countdown timer to all connected clients."""
    cr = state.current_bracket_round
    sr = state.current_sub_round

    await manager.broadcast("timer_start", {
        "bracket_round": cr,
        "sub_round": sr,
        "timer_seconds": seconds,
        "timer_start": time.time(),
        "label": label,
    })

    remaining = seconds
    try:
        while remaining > 0:
            await asyncio.sleep(1)
            remaining -= 1
            await manager.broadcast("timer_tick", {
                "bracket_round": cr,
                "sub_round": sr,
                "remaining": remaining,
            })
        await manager.broadcast("timer_end", {"bracket_round": cr, "sub_round": sr})
    except asyncio.CancelledError:
        await manager.broadcast("timer_end", {"bracket_round": cr, "sub_round": sr})
        raise


async def _start_managed_timer(seconds: int, label: str = ""):
    """Cancel any existing timer, then start a new managed timer."""
    global _timer_task
    await _cancel_existing_timer()
    _timer_task = asyncio.create_task(_run_timer(seconds, label))
```

- [ ] **Step 2: Update sub-round break timer launch (line ~352-354)**

Replace the sub-round break timer launch at the end of `run_sub_round` to use the managed timer:

```python
    # If all 3 sub-rounds done, auto-determine winners and advance
    if len(br["sub_rounds_completed"]) >= 3:
        asyncio.create_task(_complete_bracket_round(round_num))
    elif state.sub_round_delay_seconds > 0:
        # Fire a countdown break timer between sub-rounds (non-blocking)
        await _start_managed_timer(state.sub_round_delay_seconds, "sub_round_break")
```

- [ ] **Step 3: Update round break timer in `_complete_bracket_round` (line ~418-419)**

Replace the `await _run_timer(...)` call with the managed version:

```python
    elif new_matches:
        # Wait between bracket rounds before announcing the next one
        if state.round_delay_seconds > 0:
            await _start_managed_timer(state.round_delay_seconds, "round_break")
        await manager.broadcast("bracket_update", {
            "matches": new_matches,
            "current_bracket_round": state.current_bracket_round,
            "total_bracket_rounds": state.total_bracket_rounds,
            "auto_advanced": True,
        })
```

- [ ] **Step 4: Update `/api/admin/timer/start` and `/api/admin/timer/stop` endpoints**

Replace both endpoints:

```python
@router.post("/timer/start")
async def start_timer(data: dict = None, _=Depends(verify_admin)):
    seconds = data.get("timer_seconds", 120) if data else 120
    label = data.get("label", "") if data else ""
    await _start_managed_timer(seconds, label)
    return {"message": "Timer started"}


@router.post("/timer/stop")
async def stop_timer(_=Depends(verify_admin)):
    await _cancel_existing_timer()
    await manager.broadcast("timer_end", {
        "bracket_round": state.current_bracket_round,
        "sub_round": state.current_sub_round,
    })
    return {"message": "Timer stopped"}
```

- [ ] **Step 5: Commit**

```bash
git add backend/routes/admin.py
git commit -m "fix: timer lifecycle — cancel previous timer before starting new, handle CancelledError"
```

---

### Task 2: Fix Frontend Timer Reset

**Files:**
- Modify: `frontend/src/components/Timer.jsx:27-30`

- [ ] **Step 1: Reset `remaining` to `null` on `timer_end`**

In `Timer.jsx`, update the `timer_end` handler to reset state:

```javascript
        const unsub3 = subscribe('timer_end', () => {
            setActive(false);
            setRemaining(null);
            setLabel('');
        });
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Timer.jsx
git commit -m "fix: reset timer display to idle state when timer ends"
```

---

### Task 3: Fix Bracket Duplicate Generation & Self-Matching

**Files:**
- Modify: `backend/bracket.py:33-101` (`generate_bracket` function)
- Modify: `backend/bracket.py:140-200` (`advance_winners` function)
- Modify: `backend/models.py` (add `clear_bracket_data` method)

- [ ] **Step 1: Add `clear_bracket_data` method to AppState**

In `backend/models.py`, add this method to the `AppState` class (after the existing `clear_all` method):

```python
    def clear_bracket_data(self):
        """Clear all bracket-related data (matches, submissions, bracket state) but keep teams."""
        # Delete submissions from DB first (FK constraint)
        SubmissionRepository.delete_all_submissions()
        MatchRepository.delete_all_matches()

        self._matches.clear()
        self._submissions.clear()
        self.bracket_rounds.clear()
        self.current_bracket_round = 0
        self.current_sub_round = 0
        self.champion = None
        self.bracket_generated = False
        self.total_bracket_rounds = 0
```

- [ ] **Step 2: Clear existing data at the start of `generate_bracket()`**

In `backend/bracket.py`, add cleanup at the top of `generate_bracket()`:

```python
def generate_bracket():
    """Generate round 1 matches from seeded teams (standard 1v64, 2v63, etc.)."""
    # Clear any existing bracket data to prevent duplicates
    state.clear_bracket_data()

    teams = sorted(state.teams.values(), key=lambda t: t.get("seed") or 999)
    n = len(teams)
    # ... rest of function unchanged
```

- [ ] **Step 3: Deduplicate winners in `advance_winners`**

Add a deduplication guard in `advance_winners()` to prevent a team from appearing twice:

```python
    # Collect winners (deduplicate in case of data inconsistency)
    seen = set()
    winners = []
    for m in current_matches:
        wid = m.get("winner_id")
        if wid and wid not in seen:
            seen.add(wid)
            winners.append(wid)
```

Replace the existing line:
```python
    winners = [m["winner_id"] for m in current_matches if m["winner_id"]]
```

- [ ] **Step 4: Commit**

```bash
git add backend/bracket.py backend/models.py
git commit -m "fix: clear existing bracket before regenerating, deduplicate winners in advance_winners"
```

---

### Task 4: Fix Score Validation & Consistency

**Files:**
- Modify: `backend/models.py:49-53` (`ScoreOverride` model)
- Modify: `backend/bracket.py:130-132` (`determine_match_winner` score update)
- Modify: `backend/routes/admin.py:484-487` (score override team total recalc)

- [ ] **Step 1: Add range validation to `ScoreOverride`**

In `backend/models.py`, update the `ScoreOverride` class:

```python
class ScoreOverride(BaseModel):
    submission_id: str
    new_score: float = Field(..., ge=0, le=100)
    reasoning: Optional[str] = None
```

- [ ] **Step 2: Fix `determine_match_winner` to use cumulative team score calculation**

In `backend/bracket.py`, replace the winner score update (line 130-132):

```python
    # Update winner team's cumulative score from all submissions
    if match["winner_id"]:
        total_score = sum(
            s["score"] for s in state.submissions.values()
            if s["team_id"] == match["winner_id"] and s["score"] is not None
        )
        TeamRepository.update_team_score(match["winner_id"], total_score)
    # Also update loser's cumulative score
    loser_id = match["team2_id"] if match["winner_id"] == match["team1_id"] else match["team1_id"]
    if loser_id:
        loser_total = sum(
            s["score"] for s in state.submissions.values()
            if s["team_id"] == loser_id and s["score"] is not None
        )
        TeamRepository.update_team_score(loser_id, loser_total)
```

- [ ] **Step 3: Fix score override to recalculate cumulative total correctly**

In `backend/routes/admin.py`, replace the override team total calculation (lines 484-487):

```python
    team = state.teams.get(sub["team_id"])
    if team:
        # Recalculate from all submissions (not incremental delta)
        new_total = sum(
            s["score"] for s in state.submissions.values()
            if s["team_id"] == sub["team_id"] and s["score"] is not None
        )
        TeamRepository.update_team_score(sub["team_id"], new_total)
```

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/bracket.py backend/routes/admin.py
git commit -m "fix: clamp score override to 0-100, use consistent cumulative score calculation"
```

---

### Task 5: Fix Public API Security

**Files:**
- Modify: `main.py:46-49` (remove public `/api/state`)
- Modify: `backend/routes/submissions.py` (redact sensitive fields)

- [ ] **Step 1: Replace public `/api/state` with a limited endpoint**

In `main.py`, replace the `/api/state` endpoint:

```python
@app.get("/api/state")
async def get_public_state():
    """Limited public state — no response texts or reasoning."""
    return {
        "current_bracket_round": state.current_bracket_round,
        "current_sub_round": state.current_sub_round,
        "total_bracket_rounds": state.total_bracket_rounds,
        "started": state.started,
        "seeded": state.seeded,
        "bracket_generated": state.bracket_generated,
        "champion": state.champion,
    }
```

- [ ] **Step 2: Redact sensitive fields from public submission endpoints**

In `backend/routes/submissions.py`, redact response_text and reasoning:

```python
from fastapi import APIRouter
from backend.models import state

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


def _redact_submission(sub: dict) -> dict:
    """Return a submission dict with sensitive fields removed for public access."""
    return {
        "id": sub["id"],
        "team_id": sub["team_id"],
        "team_name": sub["team_name"],
        "match_id": sub["match_id"],
        "sub_round": sub["sub_round"],
        "sub_round_category": sub["sub_round_category"],
        "score": sub["score"],
        "timestamp": sub["timestamp"],
    }


@router.get("/match/{match_id}")
async def get_match_submissions(match_id: str):
    """Get all submissions for a given match, grouped by sub-round (redacted)."""
    subs = state.get_all_submissions_for_match(match_id)
    return [_redact_submission(s) for s in subs]


@router.get("/match/{match_id}/sub-round/{sub_round}")
async def get_match_sub_round_submissions(match_id: str, sub_round: int):
    """Get submissions for a specific sub-round of a match (redacted)."""
    subs = state.get_submissions_for_match_sub_round(match_id, sub_round)
    return [_redact_submission(s) for s in subs]
```

- [ ] **Step 3: Commit**

```bash
git add main.py backend/routes/submissions.py
git commit -m "fix: limit public API exposure — redact submissions, restrict /api/state"
```

---

### Task 6: Fix `setup_dummy` Argument Order

**Files:**
- Modify: `backend/routes/admin.py:526-528` (setup_dummy function)

- [ ] **Step 1: Fix the `add_team` call signature in `setup_dummy`**

In `backend/routes/admin.py`, fix the dummy setup calls:

```python
    team1 = state.add_team("Dummy Alpha", "dummy123", [{"name": "Alice", "roll": "A1"}, {"name": "Bob", "roll": "B1"}], "DUMMY")
    team2 = state.add_team("Dummy Beta", "dummy123", [{"name": "Charlie", "roll": "C1"}, {"name": "Dana", "roll": "D1"}], "DUMMY")
```

The current code passes `["Alice", "Bob"]` as the `password` parameter — this is wrong. The signature is `add_team(name, password, members, endpoint_url)`.

- [ ] **Step 2: Commit**

```bash
git add backend/routes/admin.py
git commit -m "fix: correct add_team argument order in setup_dummy"
```

---

### Task 7: Fix Bracket Frontend — Ensure Clean Data Flow

**Files:**
- Modify: `frontend/src/components/Bracket.jsx:49-58` (useEffect data fetch)

- [ ] **Step 1: Deduplicate matches in Bracket component as a safety net**

Even with backend fixes, add client-side deduplication in `Bracket.jsx` to be safe:

```javascript
    useEffect(() => {
        fetchBracket();
        const unsubs = [
            subscribe('bracket_update', () => fetchBracket()),
            subscribe('match_scored', () => fetchBracket()),
            subscribe('bracket_round_complete', () => fetchBracket()),
            subscribe('match_result', () => fetchBracket()),
            subscribe('champion', (data) => { setChampion(data.team_id); fetchBracket(); }),
            subscribe('reset', () => { setMatches([]); setChampion(null); }),
        ];
        return () => unsubs.forEach(fn => fn());
    }, [subscribe]);
```

Also add deduplication in `fetchBracket`:

```javascript
    const fetchBracket = async () => {
        try {
            const res = await fetch('/api/bracket');
            const data = await res.json();
            // Deduplicate matches by id (safety net)
            const seen = new Set();
            const unique = (data.matches || []).filter(m => {
                if (seen.has(m.id)) return false;
                seen.add(m.id);
                return true;
            });
            setMatches(unique);
            setChampion(data.champion || null);
        } catch (e) {
            console.error('Failed to fetch bracket:', e);
        }
    };
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Bracket.jsx
git commit -m "fix: deduplicate matches in bracket display, subscribe to match_result and reset events"
```

---

## Summary of All Changes

| Issue | Root Cause | Fix Location | Fix |
|-------|-----------|--------------|-----|
| Timer overlap | Untracked internal timers | admin.py | `_start_managed_timer` cancels previous before starting new |
| Timer unstoppable | `_run_timer` ignores CancelledError | admin.py | Wrap loop in try/except, broadcast timer_end on cancel |
| Timer display stuck | `remaining` not reset on end | Timer.jsx | Set `remaining` to `null` in timer_end handler |
| Self-matching | Duplicate matches from double generate | bracket.py | `clear_bracket_data()` at start of `generate_bracket()` |
| Self-matching | No winner dedup in advance | bracket.py | Deduplicate winners set before pairing |
| Score > 300 | No validation on override | models.py | `Field(..., ge=0, le=100)` on ScoreOverride |
| Score inconsistency | Conflicting total_score calculations | bracket.py, admin.py | Consistent cumulative recalculation everywhere |
| Bracket duplicates (FE) | No client dedup | Bracket.jsx | Filter by unique match.id |
| Missing event subs | No reset/match_result handlers | Bracket.jsx | Subscribe to `reset` and `match_result` |
| API data leak | `/api/state` fully public | main.py | Return limited public state |
| API data leak | Submissions expose responses | submissions.py | Redact response_text and reasoning |
| Dummy setup crash | Wrong arg order in add_team | admin.py | Fix parameter positions |
