import asyncio
import os
import secrets
import time
import httpx
from fastapi import APIRouter, HTTPException, Depends, Header
from backend.models import state, ScoreOverride, SubRoundConfig, SUB_ROUND_CATEGORIES
from backend.gemini_judge import judge_submission, judge_match_submission
from backend.ws_manager import manager
from backend.bracket import seed_teams, generate_bracket, advance_winners, determine_match_winner
from backend.logger import log_llm_fetch, log_judge_result
from backend.questions import ROUND_QUESTIONS
from backend.database import TeamRepository

router = APIRouter(prefix="/api/admin", tags=["admin"])

_timer_task: asyncio.Task | None = None
_admin_tokens: set[str] = set()


# ── Shared timer helper ──────────────────────────────────────────────

async def _cancel_existing_timer():
    """Cancel the currently running timer task (if any) and wait for it to finish."""
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
    except asyncio.CancelledError:
        await manager.broadcast("timer_end", {"bracket_round": cr, "sub_round": sr})
        raise

    await manager.broadcast("timer_end", {"bracket_round": cr, "sub_round": sr})


async def _start_managed_timer(seconds: int, label: str = ""):
    """Cancel any existing timer, then start a new managed timer task."""
    global _timer_task
    await _cancel_existing_timer()
    _timer_task = asyncio.create_task(_run_timer(seconds, label))


# ── Admin Auth ──────────────────────────────────────────────────────

def _get_admin_password() -> str:
    pw = os.getenv("ADMIN_PASSWORD")
    if not pw:
        raise RuntimeError("ADMIN_PASSWORD not set in environment")
    return pw


async def verify_admin(authorization: str = Header(None)):
    """Dependency that checks Bearer token on protected admin routes."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    if token not in _admin_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.post("/login")
async def admin_login(data: dict):
    """Authenticate admin with password, return a session token."""
    password = data.get("password", "")
    if password != _get_admin_password():
        raise HTTPException(status_code=401, detail="Wrong password")
    token = secrets.token_urlsafe(32)
    _admin_tokens.add(token)
    return {"token": token}


@router.get("/questions")
async def get_questions(_=Depends(verify_admin)):
    """Return predefined round questions."""
    return ROUND_QUESTIONS


@router.get("/state")
async def get_full_state(_=Depends(verify_admin)):
    """Full state dump for admin."""
    return state.to_dict()


# ── Settings ─────────────────────────────────────────────────────────

@router.post("/settings")
async def update_settings(data: dict, _=Depends(verify_admin)):
    """Update configurable timing settings (sub-round and round delays)."""
    if "sub_round_delay_seconds" in data:
        val = int(data["sub_round_delay_seconds"])
        if val < 0:
            raise HTTPException(status_code=400, detail="sub_round_delay_seconds must be >= 0")
        state.sub_round_delay_seconds = val
    if "round_delay_seconds" in data:
        val = int(data["round_delay_seconds"])
        if val < 0:
            raise HTTPException(status_code=400, detail="round_delay_seconds must be >= 0")
        state.round_delay_seconds = val
    return {
        "sub_round_delay_seconds": state.sub_round_delay_seconds,
        "round_delay_seconds": state.round_delay_seconds,
    }


# ── Seeding & Bracket ────────────────────────────────────────────────

@router.post("/seed")
async def seed(data: dict = None, _=Depends(verify_admin)):
    """Seed teams randomly or manually."""
    if len(state.teams) == 0:
        raise HTTPException(status_code=400, detail="No teams registered")
    mode = data.get("mode", "random") if data else "random"
    order = data.get("order") if data else None
    teams = seed_teams(mode=mode, order=order)
    await manager.broadcast("seeding_update", {"teams": teams, "seeded": True})
    return {"message": f"Seeded {len(teams)} teams", "teams": teams}


@router.post("/generate-bracket")
async def gen_bracket(_=Depends(verify_admin)):
    """Generate tournament bracket from seeded teams."""
    if not state.seeded:
        raise HTTPException(status_code=400, detail="Teams must be seeded first")
    matches = generate_bracket()
    await manager.broadcast("bracket_update", {
        "matches": matches,
        "current_bracket_round": state.current_bracket_round,
        "total_bracket_rounds": state.total_bracket_rounds,
    })
    return {"message": f"Generated bracket with {len(matches)} matches in round 1", "matches": matches}


# ── Sub-Round Management ─────────────────────────────────────────────

@router.post("/bracket-round/{round_num}/sub-round/{sub_round}/prompt")
async def set_sub_round_prompt(round_num: int, sub_round: int, config: SubRoundConfig, _=Depends(verify_admin)):
    """Set a question for a sub-round — applies to ALL matches in this bracket round."""
    if round_num not in state.bracket_rounds:
        raise HTTPException(status_code=400, detail=f"Bracket round {round_num} doesn't exist")
    if sub_round not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Sub-round must be 1, 2, or 3")

    br = state.bracket_rounds[round_num]
    br["sub_round_prompts"][sub_round] = config.prompt

    # Also store on each match dict for convenience
    for match in state.get_matches_for_round(round_num):
        match["sub_round_prompts"][sub_round] = config.prompt
        state.update_match(match)

    state.current_bracket_round = round_num
    state.current_sub_round = sub_round
    state.started = True

    await manager.broadcast("sub_round_prompt_set", {
        "bracket_round": round_num,
        "sub_round": sub_round,
        "category": SUB_ROUND_CATEGORIES[sub_round],
        "prompt": config.prompt,
        "timer_seconds": config.timer_seconds,
    })
    return {"message": f"Prompt set for R{round_num} sub-round {sub_round}: {SUB_ROUND_CATEGORIES[sub_round]}"}


@router.post("/bracket-round/{round_num}/sub-round/{sub_round}/run")
async def run_sub_round(round_num: int, sub_round: int, _=Depends(verify_admin)):
    """
    For ALL matches in bracket round: fetch responses from both teams' endpoints,
    then judge with Gemini. All matches run concurrently.
    """
    if round_num not in state.bracket_rounds:
        raise HTTPException(status_code=400, detail=f"Bracket round {round_num} doesn't exist")
    if sub_round not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Sub-round must be 1, 2, or 3")

    br = state.bracket_rounds[round_num]
    prompt = br["sub_round_prompts"].get(sub_round)
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt set for this sub-round")

    matches = state.get_matches_for_round(round_num)
    # Filter to matches that actually have 2 teams (skip byes)
    active_matches = [m for m in matches if m["team1_id"] and m["team2_id"] and not m.get("winner_id")]

    await manager.broadcast("sub_round_start", {
        "bracket_round": round_num,
        "sub_round": sub_round,
        "category": SUB_ROUND_CATEGORIES[sub_round],
        "total_matches": len(active_matches),
    })

    category = SUB_ROUND_CATEGORIES[sub_round]

    async def process_match(match: dict):
        """Fetch + judge both teams in this match for the given sub-round."""
        team1 = state.teams.get(match["team1_id"])
        team2 = state.teams.get(match["team2_id"])
        if not team1 or not team2:
            return

        # Create submission records
        for team in [team1, team2]:
            existing = state.get_submission_for_team_match_sub_round(team["id"], match["id"], sub_round)
            if not existing:
                state.add_submission(team["id"], match["id"], sub_round, prompt)

        # Fetch from both endpoints concurrently
        async def fetch_one(team: dict):
            sub = state.get_submission_for_team_match_sub_round(team["id"], match["id"], sub_round)
            if not sub:
                return

            if team["endpoint_url"] == "DUMMY":
                # Special case for testing with a dummy endpoint
                dummy_text = f"[DUMMY] This is a simulated response from {team['name']} for prompt: {prompt[:30]}..."
                sub["response_text"] = dummy_text
                sub["timestamp"] = __import__("datetime").datetime.now().isoformat()
                state.update_submission(sub)
                log_llm_fetch(team["name"], "DUMMY", prompt, dummy_text, None)
                return

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        team["endpoint_url"],
                        json={"prompt": prompt},
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    if isinstance(data, str):
                        response_text = data
                    elif isinstance(data, dict):
                        response_text = data.get("response") or data.get("text") or data.get("output") or data.get("generated_text") or str(data)
                    else:
                        response_text = str(data)
                    sub["response_text"] = response_text
                    sub["timestamp"] = __import__("datetime").datetime.now().isoformat()
                    state.update_submission(sub)
                    log_llm_fetch(team["name"], team["endpoint_url"], prompt, response_text, None)
            except Exception as e:
                sub["fetch_error"] = str(e)[:200]
                sub["timestamp"] = __import__("datetime").datetime.now().isoformat()
                state.update_submission(sub)
                log_llm_fetch(team["name"], team["endpoint_url"], prompt, None, str(e)[:200])

        await asyncio.gather(fetch_one(team1), fetch_one(team2))

        await manager.broadcast("match_fetched", {
            "match_id": match["id"],
            "bracket_round": round_num,
            "sub_round": sub_round,
            "team1_name": team1["name"],
            "team2_name": team2["name"],
        })

        # Judge both responses with Gemini (single comparative call)
        t1_sub = state.get_submission_for_team_match_sub_round(team1["id"], match["id"], sub_round)
        t2_sub = state.get_submission_for_team_match_sub_round(team2["id"], match["id"], sub_round)

        t1_response = t1_sub["response_text"] if t1_sub else None
        t2_response = t2_sub["response_text"] if t2_sub else None

        judge_result = await judge_match_submission(
            prompt, t1_response or "", t2_response or "",
            team1["name"], team2["name"], category,
        )

        # Store scores on submissions
        if t1_sub:
            t1_sub["score"] = judge_result["team_a_score"] if t1_response else 0
            t1_sub["reasoning"] = judge_result["reasoning"]
            state.update_submission(t1_sub)
            log_judge_result(team1["name"], category, t1_sub["score"], t1_sub["reasoning"])
        if t2_sub:
            t2_sub["score"] = judge_result["team_b_score"] if t2_response else 0
            t2_sub["reasoning"] = judge_result["reasoning"]
            state.update_submission(t2_sub)
            log_judge_result(team2["name"], category, t2_sub["score"], t2_sub["reasoning"])

        # Update cumulative team scores in database
        for tid in [team1["id"], team2["id"]]:
            total_score = sum(
                s["score"] for s in state.submissions.values()
                if s["team_id"] == tid and s["score"] is not None
            )
            TeamRepository.update_team_score(tid, total_score)

        # Update match sub-round totals
        scores = state.get_match_total_scores(match["id"])
        match["team1_total"] = scores["team1_total"]
        match["team2_total"] = scores["team2_total"]
        state.update_match(match)

        await manager.broadcast("match_scored", {
            "match_id": match["id"],
            "bracket_round": round_num,
            "sub_round": sub_round,
            "team1_name": team1["name"],
            "team2_name": team2["name"],
            "team1_sub_score": t1_sub["score"] if t1_sub else 0,
            "team2_sub_score": t2_sub["score"] if t2_sub else 0,
            "team1_total": match["team1_total"],
            "team2_total": match["team2_total"],
        })

        # Broadcast match_update for live team view (Change 2)
        await manager.broadcast("match_update", {
            "match_id": match["id"],
            "sub_round": sub_round,
            "sub_round_label": SUB_ROUND_CATEGORIES[sub_round],
            "prompt": prompt,
            "team1_id": team1["id"],
            "team2_id": team2["id"],
            "team1_name": team1["name"],
            "team2_name": team2["name"],
            "team1_response": t1_response or "",
            "team2_response": t2_response or "",
            "team1_score": t1_sub["score"] if t1_sub else 0,
            "team2_score": t2_sub["score"] if t2_sub else 0,
            "team1_total": match["team1_total"],
            "team2_total": match["team2_total"],
            "reasoning": judge_result["reasoning"],
        })

    # Run ALL matches concurrently
    await asyncio.gather(*[process_match(m) for m in active_matches])

    # Mark sub-round as complete
    if sub_round not in br["sub_rounds_completed"]:
        br["sub_rounds_completed"].append(sub_round)
    for match in active_matches:
        if sub_round not in match["sub_rounds_completed"]:
            match["sub_rounds_completed"].append(sub_round)
        state.update_match(match)

    await manager.broadcast("sub_round_complete", {
        "bracket_round": round_num,
        "sub_round": sub_round,
        "sub_rounds_completed": br["sub_rounds_completed"],
    })

    # If all 3 sub-rounds done, auto-determine winners and advance
    if len(br["sub_rounds_completed"]) >= 3:
        asyncio.create_task(_complete_bracket_round(round_num))
    elif state.sub_round_delay_seconds > 0:
        # Fire a countdown break timer between sub-rounds (non-blocking)
        await _start_managed_timer(state.sub_round_delay_seconds, "sub_round_break")

    return {
        "message": f"Sub-round {sub_round} ({SUB_ROUND_CATEGORIES[sub_round]}) completed for {len(active_matches)} matches",
        "sub_rounds_completed": br["sub_rounds_completed"],
    }


async def _complete_bracket_round(round_num: int):
    """After all 3 sub-rounds: determine winners, eliminate losers, advance to next bracket round."""
    matches = state.get_matches_for_round(round_num)

    # Determine winners for each match and broadcast match_result per match
    results = []
    for match in matches:
        if not match.get("winner_id"):
            determine_match_winner(match["id"])

        # Build per-sub-round breakdown
        breakdown = []
        for sr in [1, 2, 3]:
            t1_sub = state.get_submission_for_team_match_sub_round(
                match["team1_id"], match["id"], sr) if match["team1_id"] else None
            t2_sub = state.get_submission_for_team_match_sub_round(
                match["team2_id"], match["id"], sr) if match["team2_id"] else None
            breakdown.append({
                "sub_round": sr,
                "category": SUB_ROUND_CATEGORIES[sr],
                "team_a_score": t1_sub["score"] if t1_sub and t1_sub["score"] is not None else 0,
                "team_b_score": t2_sub["score"] if t2_sub and t2_sub["score"] is not None else 0,
            })

        result_data = {
            "match_id": match["id"],
            "team_a_name": match["team1_name"],
            "team_b_name": match["team2_name"],
            "team_a_total": match["team1_total"],
            "team_b_total": match["team2_total"],
            "winner_name": match["winner_name"],
            "sub_round_breakdown": breakdown,
        }
        results.append(result_data)

        # Broadcast per-match result
        await manager.broadcast("match_result", result_data)

    await manager.broadcast("bracket_round_complete", {
        "bracket_round": round_num,
        "results": results,
    })

    # Advance winners to next round
    new_matches = advance_winners(round_num)

    if state.champion:
        champ = state.teams.get(state.champion)
        if champ:
            await manager.broadcast("champion", {
                "team_id": champ["id"],
                "team_name": champ["name"],
                "total_score": champ["total_score"],
            })
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


# ── Manual completion trigger ────────────────────────────────────────

@router.post("/bracket-round/{round_num}/complete")
async def complete_bracket_round(round_num: int, _=Depends(verify_admin)):
    """Manually trigger bracket round completion (if auto didn't fire)."""
    if round_num not in state.bracket_rounds:
        raise HTTPException(status_code=400, detail=f"Bracket round {round_num} doesn't exist")
    await _complete_bracket_round(round_num)
    return {
        "message": f"Bracket round {round_num} completed",
        "champion": state.champion,
        "next_round": state.current_bracket_round,
    }


# ── Timer ────────────────────────────────────────────────────────────

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


# ── Score Override ───────────────────────────────────────────────────

@router.post("/score/override")
async def override_score(override: ScoreOverride, _=Depends(verify_admin)):
    sub = state.submissions.get(override.submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    old_score = sub["score"] or 0
    sub["score"] = override.new_score
    if override.reasoning:
        sub["reasoning"] = override.reasoning
    state.update_submission(sub)

    team = state.teams.get(sub["team_id"])
    if team:
        new_total = team["total_score"] - old_score + override.new_score
        TeamRepository.update_team_score(sub["team_id"], new_total)

    # Update match totals
    match = state.matches.get(sub["match_id"])
    if match:
        scores = state.get_match_total_scores(match["id"])
        match["team1_total"] = scores["team1_total"]
        match["team2_total"] = scores["team2_total"]
        state.update_match(match)

    await manager.broadcast("score_update", {"submission": sub})
    return {"message": "Score overridden", "submission": sub}


# ── Test Endpoint ────────────────────────────────────────────────────

@router.post("/test-endpoint")
async def test_endpoint(data: dict, _=Depends(verify_admin)):
    url = data.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                json={"prompt": "Hello! This is a test. Please respond with a short greeting."},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return {"status": "ok", "response": response.json(), "status_code": response.status_code}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


# ── Dummy Setup ──────────────────────────────────────────────────────

@router.post("/setup-dummy")
async def setup_dummy(_=Depends(verify_admin)):
    """Clear state, register 2 dummy teams, seed, and generate bracket to prepare for testing."""
    state.__init__()
    team1 = state.add_team("Dummy Alpha 🚀", ["Alice", "Bob"], "DUMMY")
    team2 = state.add_team("Dummy Beta 💥", ["Charlie", "Dana"], "DUMMY")
    teams = seed_teams(mode="random")
    matches = generate_bracket()

    await manager.broadcast("reset", {})
    await manager.broadcast("team_registered", team1)
    await manager.broadcast("team_registered", team2)
    await manager.broadcast("seeding_update", {"teams": teams, "seeded": True})
    await manager.broadcast("bracket_update", {
        "matches": matches,
        "current_bracket_round": state.current_bracket_round,
        "total_bracket_rounds": state.total_bracket_rounds,
    })
    return {"message": "Dummy battle setup complete", "teams": teams, "matches": matches}


# ── Restart Bracket Round ─────────────────────────────────────────────

@router.post("/bracket-round/{round_num}/reset")
async def reset_bracket_round(round_num: int, _=Depends(verify_admin)):
    """Wipe out all submissions, scores, and progress for the current bracket round so it can be re-run."""
    if round_num not in state.bracket_rounds:
        raise HTTPException(status_code=400, detail="Bracket round not found")

    br = state.bracket_rounds[round_num]
    br["sub_rounds_completed"] = []
    br["sub_round_prompts"] = {}
    br["completed"] = False

    matches = state.get_matches_for_round(round_num)
    match_ids = {m["id"] for m in matches}

    # Delete all submissions tied to this round's matches (from memory and database)
    from backend.database import SubmissionRepository
    keys_to_delete = [
        k for k, sub in state.submissions.items()
        if sub["match_id"] in match_ids
    ]
    for k in keys_to_delete:
        del state._submissions[k]
    for match_id in match_ids:
        SubmissionRepository.delete_submissions_for_match(match_id)

    # Reset match totals
    for match in matches:
        match["team1_total"] = 0
        match["team2_total"] = 0
        match["winner_id"] = None
        match["winner_name"] = None
        match["sub_round_prompts"] = {1: None, 2: None, 3: None}
        match["sub_rounds_completed"] = []
        state.update_match(match)

    # Recalculate global team scores
    for match in matches:
        for tid in [match["team1_id"], match["team2_id"]]:
            if not tid: continue
            total_score = sum(
                s["score"] for s in state.submissions.values()
                if s["team_id"] == tid and s["score"] is not None
            )
            TeamRepository.update_team_score(tid, total_score)

    await manager.broadcast("bracket_update", {
        "matches": list(state.matches.values()),
        "current_bracket_round": state.current_bracket_round,
        "total_bracket_rounds": state.total_bracket_rounds,
    })

    return {"message": f"Bracket round {round_num} successfully reset."}


# ── Reset ────────────────────────────────────────────────────────────

@router.post("/reset")
async def reset(_=Depends(verify_admin)):
    state.clear_all()
    await manager.broadcast("reset", {})
    return {"message": "State reset"}
