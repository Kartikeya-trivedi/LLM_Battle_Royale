import random
import uuid
import math
from backend.models import state
from backend.database import TeamRepository


def seed_teams(mode: str = "random", order: list[str] | None = None):
    """Assign seeds 1-N to all registered teams."""
    teams = list(state.teams.values())

    if mode == "manual" and order:
        sorted_teams = []
        for tid in order:
            if tid in state.teams:
                sorted_teams.append(state.teams[tid])
        remaining = [t for t in teams if t["id"] not in order]
        random.shuffle(remaining)
        sorted_teams.extend(remaining)
        teams = sorted_teams
    else:
        random.shuffle(teams)

    for i, team in enumerate(teams):
        team["seed"] = i + 1
        # Update seed in the database
        TeamRepository.set_team_seed(team["id"], i + 1)

    state.seeded = True
    return teams


def generate_bracket():
    """Generate round 1 matches from seeded teams (standard 1v64, 2v63, etc.)."""
    teams = sorted(state.teams.values(), key=lambda t: t.get("seed") or 999)
    n = len(teams)

    bracket_size = 2 ** math.ceil(math.log2(n)) if n > 0 else 0

    matches = []
    num_matches = bracket_size // 2

    for i in range(num_matches):
        team1 = teams[i] if i < n else None
        team2 = teams[bracket_size - 1 - i] if (bracket_size - 1 - i) < n else None

        match_id = str(uuid.uuid4())[:8]
        match = {
            "id": match_id,
            "round_number": 1,
            "match_index": i,
            "team1_id": team1["id"] if team1 else None,
            "team2_id": team2["id"] if team2 else None,
            "team1_name": team1["name"] if team1 else None,
            "team2_name": team2["name"] if team2 else None,
            "team1_seed": team1.get("seed") if team1 else None,
            "team2_seed": team2.get("seed") if team2 else None,
            "team1_total": 0,
            "team2_total": 0,
            "sub_round_prompts": {1: None, 2: None, 3: None},
            "sub_rounds_completed": [],  # [1, 2, 3] as they complete
            "winner_id": None,
            "winner_name": None,
            "completed": False,
        }

        # Auto-advance if only one team (bye)
        if team1 and not team2:
            match["winner_id"] = team1["id"]
            match["winner_name"] = team1["name"]
            match["completed"] = True
        elif team2 and not team1:
            match["winner_id"] = team2["id"]
            match["winner_name"] = team2["name"]
            match["completed"] = True

        state.add_match(match)
        matches.append(match)

    # Calculate total bracket rounds needed
    total_rounds = math.ceil(math.log2(bracket_size)) if bracket_size > 0 else 0
    state.total_bracket_rounds = total_rounds

    # Initialize bracket round metadata
    for r in range(1, total_rounds + 1):
        num_matches_in_round = bracket_size // (2 ** r)
        state.bracket_rounds[r] = {
            "number": r,
            "total_matches": num_matches_in_round,
            "sub_round_prompts": {1: None, 2: None, 3: None},
            "sub_rounds_completed": [],
            "completed": False,
            "active": r == 1,
        }

    state.current_bracket_round = 1
    state.current_sub_round = 0
    state.bracket_generated = True
    state.started = True

    return matches


def determine_match_winner(match_id: str) -> dict:
    """Determine winner of a match based on total scores across 3 sub-rounds."""
    match = state.matches[match_id]
    if match.get("winner_id"):
        return match  # Already has winner (bye)

    scores = state.get_match_total_scores(match_id)
    t1 = scores["team1_total"]
    t2 = scores["team2_total"]

    match["team1_total"] = t1
    match["team2_total"] = t2

    if t1 > t2:
        match["winner_id"] = match["team1_id"]
        match["winner_name"] = match["team1_name"]
        if match["team2_id"]:
            TeamRepository.eliminate_team(match["team2_id"])
    elif t2 > t1:
        match["winner_id"] = match["team2_id"]
        match["winner_name"] = match["team2_name"]
        if match["team1_id"]:
            TeamRepository.eliminate_team(match["team1_id"])
    else:
        # Tie-break: random coin flip (fair for both teams)
        coin = random.choice(["team1", "team2"])
        if coin == "team1":
            match["winner_id"] = match["team1_id"]
            match["winner_name"] = match["team1_name"]
            if match["team2_id"]:
                TeamRepository.eliminate_team(match["team2_id"])
        else:
            match["winner_id"] = match["team2_id"]
            match["winner_name"] = match["team2_name"]
            if match["team1_id"]:
                TeamRepository.eliminate_team(match["team1_id"])

    match["completed"] = True

    # Update winner team's total score
    if match["winner_id"]:
        TeamRepository.update_team_score(match["winner_id"], max(t1, t2))

    # Persist match changes to database
    state.update_match(match)

    return match


def advance_winners(round_number: int) -> list[dict]:
    """Take winners from bracket round N, create matches for round N+1."""
    current_matches = state.get_matches_for_round(round_number)

    # Ensure all matches have winners
    for m in current_matches:
        if not m.get("winner_id"):
            determine_match_winner(m["id"])

    # Mark bracket round as completed
    state.bracket_rounds[round_number]["completed"] = True
    state.bracket_rounds[round_number]["active"] = False

    # Collect winners
    winners = [m["winner_id"] for m in current_matches if m["winner_id"]]

    if len(winners) <= 1:
        if winners:
            state.champion = winners[0]
        return []

    next_round = round_number + 1

    # Guard: if next-round matches already exist, don't create duplicates
    existing_next = state.get_matches_for_round(next_round)
    if existing_next:
        return existing_next

    new_matches = []
    for i in range(0, len(winners), 2):
        w1 = winners[i]
        w2 = winners[i + 1] if i + 1 < len(winners) else None

        match_id = str(uuid.uuid4())[:8]
        match = {
            "id": match_id,
            "round_number": next_round,
            "match_index": i // 2,
            "team1_id": w1,
            "team2_id": w2,
            "team1_name": state.teams[w1]["name"] if w1 else None,
            "team2_name": state.teams[w2]["name"] if w2 else None,
            "team1_seed": state.teams[w1].get("seed") if w1 else None,
            "team2_seed": state.teams[w2].get("seed") if w2 else None,
            "team1_total": 0,
            "team2_total": 0,
            "sub_round_prompts": {1: None, 2: None, 3: None},
            "sub_rounds_completed": [],
            "winner_id": None,
            "winner_name": None,
            "completed": False,
        }

        # Bye
        if w1 and not w2:
            match["winner_id"] = w1
            match["winner_name"] = state.teams[w1]["name"]
            match["completed"] = True

        state.add_match(match)
        new_matches.append(match)

    state.current_bracket_round = next_round
    state.current_sub_round = 0
    state.bracket_rounds[next_round]["active"] = True

    return new_matches
