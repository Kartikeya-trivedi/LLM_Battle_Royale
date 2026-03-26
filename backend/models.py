from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import uuid
import re
from backend.database import TeamRepository, MatchRepository, SubmissionRepository


# ── Pydantic request/response models ────────────────────────────────

class TeamMember(BaseModel):
    name: str
    roll: str

    @field_validator('roll')
    @classmethod
    def validate_roll(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9]+$', v):
            raise ValueError('Roll number must be alphanumeric')
        return v


class TeamCreate(BaseModel):
    name: str
    password: str = Field(..., min_length=4)  # Team password for authentication
    members: list[TeamMember] = Field(..., min_length=1, max_length=4)
    endpoint_url: str  # Team's /generate endpoint URL


class TeamLogin(BaseModel):
    name: str
    password: str


class TeamEndpointUpdate(BaseModel):
    endpoint_url: str


class TeamOut(BaseModel):
    id: str
    name: str
    members: list[TeamMember]
    endpoint_url: str
    eliminated: bool = False
    total_score: float = 0
    seed: Optional[int] = None


class ScoreOverride(BaseModel):
    submission_id: str
    new_score: float
    reasoning: Optional[str] = None


class SubRoundConfig(BaseModel):
    prompt: str
    timer_seconds: int = 120


# ── Sub-round categories (same for every match) ────────────────────
SUB_ROUND_CATEGORIES = {
    1: "Complex Puzzle",
    2: "Math",
    3: "General Knowledge",
}


# ── In-memory application state with database persistence ───────────

class AppState:
    def __init__(self):
        # In-memory cache - synced with database
        self._matches: dict[str, dict] = {}
        self._submissions: dict[str, dict] = {}
        self.bracket_rounds: dict[int, dict] = {}  # bracket round metadata
        self.current_bracket_round: int = 0
        self.current_sub_round: int = 0
        self.champion: Optional[str] = None
        self.started: bool = False
        self.seeded: bool = False
        self.bracket_generated: bool = False
        self.total_bracket_rounds: int = 0
        # Configurable inter-round delays (seconds)
        self.sub_round_delay_seconds: int = 30
        self.round_delay_seconds: int = 300
        # Registration & endpoint editing locks
        self.registration_open: bool = True
        self.endpoint_editing_open: bool = True

        # Load existing data from database
        self._load_from_database()

    def _load_from_database(self):
        """Load matches and submissions from the database into memory."""
        try:
            # Load matches
            all_matches = MatchRepository.get_all_matches()
            self._matches = {m["id"]: m for m in all_matches}

            # Load submissions
            all_submissions = SubmissionRepository.get_all_submissions()
            self._submissions = {s["id"]: s for s in all_submissions}

            # Check if we have existing data to restore state
            if self._matches:
                self.bracket_generated = True
                self.started = True
                max_round = max(m["round_number"] for m in self._matches.values())
                self.current_bracket_round = max_round

            # Check if teams are seeded
            teams = TeamRepository.get_all_teams()
            if teams and any(t.get("seed") for t in teams):
                self.seeded = True
        except Exception as e:
            print(f"Warning: Could not load from database: {e}")

    @property
    def matches(self) -> dict[str, dict]:
        """Return matches dictionary."""
        return self._matches

    @property
    def submissions(self) -> dict[str, dict]:
        """Return submissions dictionary."""
        return self._submissions

    @property
    def teams(self) -> dict[str, dict]:
        """Return teams as a dictionary keyed by ID for backward compatibility."""
        all_teams = TeamRepository.get_all_teams()
        return {t["id"]: t for t in all_teams}

    def add_team(self, name: str, password: str, members: list[str], endpoint_url: str) -> dict:
        """Add a team using the database repository."""
        return TeamRepository.create_team(name, password, members, endpoint_url)

    def get_team_by_name(self, name: str) -> Optional[dict]:
        """Get a team by name using the database repository."""
        return TeamRepository.get_team_by_name(name)

    def get_team_by_id(self, team_id: str) -> Optional[dict]:
        """Get a team by ID using the database repository."""
        return TeamRepository.get_team_by_id(team_id)

    def authenticate_team(self, name: str, password: str) -> Optional[dict]:
        """Authenticate a team using the database repository."""
        return TeamRepository.authenticate_team(name, password)

    def get_all_teams(self) -> list[dict]:
        """Get all teams using the database repository."""
        return TeamRepository.get_all_teams()

    def get_active_teams(self) -> list[dict]:
        """Get active teams using the database repository."""
        return TeamRepository.get_active_teams()

    def add_match(self, match: dict) -> dict:
        """Add a match to both memory and database."""
        self._matches[match["id"]] = match
        MatchRepository.create_match(match)
        return match

    def update_match(self, match: dict):
        """Update a match in both memory and database."""
        self._matches[match["id"]] = match
        MatchRepository.update_match(match)

    def get_matches_for_round(self, round_number: int) -> list[dict]:
        """Return all matches for a given bracket round, sorted by match_index."""
        return sorted(
            [m for m in self._matches.values() if m["round_number"] == round_number],
            key=lambda m: m["match_index"],
        )

    def get_match_by_id(self, match_id: str) -> Optional[dict]:
        return self._matches.get(match_id)

    def add_submission(self, team_id: str, match_id: str, sub_round: int, prompt_sent: str) -> dict:
        """Add a submission for a team in a specific match + sub-round."""
        sub_id = str(uuid.uuid4())[:8]
        team = self.get_team_by_id(team_id)
        team_name = team["name"] if team else "Unknown Team"

        submission = {
            "id": sub_id,
            "team_id": team_id,
            "team_name": team_name,
            "match_id": match_id,
            "sub_round": sub_round,
            "sub_round_category": SUB_ROUND_CATEGORIES[sub_round],
            "prompt_sent": prompt_sent,
            "response_text": None,
            "timestamp": None,
            "score": None,
            "reasoning": None,
            "fetch_error": None,
        }
        self._submissions[sub_id] = submission
        SubmissionRepository.create_submission(submission)
        return submission

    def update_submission(self, submission: dict):
        """Update a submission in both memory and database."""
        self._submissions[submission["id"]] = submission
        SubmissionRepository.update_submission(submission)

    def get_submissions_for_match_sub_round(self, match_id: str, sub_round: int) -> list[dict]:
        return [
            s for s in self._submissions.values()
            if s["match_id"] == match_id and s["sub_round"] == sub_round
        ]

    def get_submission_for_team_match_sub_round(self, team_id: str, match_id: str, sub_round: int) -> Optional[dict]:
        for s in self._submissions.values():
            if s["team_id"] == team_id and s["match_id"] == match_id and s["sub_round"] == sub_round:
                return s
        return None

    def get_all_submissions_for_match(self, match_id: str) -> list[dict]:
        return sorted(
            [s for s in self._submissions.values() if s["match_id"] == match_id],
            key=lambda s: (s["sub_round"], s["team_name"]),
        )

    def get_match_total_scores(self, match_id: str) -> dict:
        """Calculate total scores across all 3 sub-rounds for each team in a match."""
        match = self._matches.get(match_id)
        if not match:
            return {}
        team1_total = 0
        team2_total = 0
        for s in self._submissions.values():
            if s["match_id"] == match_id and s["score"] is not None:
                if s["team_id"] == match.get("team1_id"):
                    team1_total += s["score"]
                elif s["team_id"] == match.get("team2_id"):
                    team2_total += s["score"]
        return {
            "team1_total": team1_total,
            "team2_total": team2_total,
        }

    def get_standings(self) -> list[dict]:
        """Return all teams sorted by total score, active first."""
        teams = self.get_all_teams()
        teams.sort(key=lambda t: (not t["eliminated"], t["total_score"]), reverse=True)
        return teams

    def clear_all(self):
        """Clear all data from memory and database."""
        self._matches.clear()
        self._submissions.clear()
        self.bracket_rounds.clear()
        self.current_bracket_round = 0
        self.current_sub_round = 0
        self.champion = None
        self.started = False
        self.seeded = False
        self.bracket_generated = False
        self.total_bracket_rounds = 0
        self.sub_round_delay_seconds = 30
        self.round_delay_seconds = 300
        self.registration_open = True
        self.endpoint_editing_open = True

        # Clear database
        SubmissionRepository.delete_all_submissions()
        MatchRepository.delete_all_matches()

    def to_dict(self) -> dict:
        return {
            "teams": self.get_all_teams(),
            "submissions": list(self._submissions.values()),
            "matches": list(self._matches.values()),
            "bracket_rounds": self.bracket_rounds,
            "current_bracket_round": self.current_bracket_round,
            "current_sub_round": self.current_sub_round,
            "total_bracket_rounds": self.total_bracket_rounds,
            "started": self.started,
            "seeded": self.seeded,
            "bracket_generated": self.bracket_generated,
            "champion": self.champion,
            "sub_round_delay_seconds": self.sub_round_delay_seconds,
            "round_delay_seconds": self.round_delay_seconds,
            "registration_open": self.registration_open,
            "endpoint_editing_open": self.endpoint_editing_open,
        }


# Singleton state
state = AppState()
