import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import bcrypt
import uuid
import json
import os
from typing import Optional, Dict, List
from contextlib import contextmanager
from dotenv import load_dotenv
load_dotenv()
db_pass = os.getenv("POSTGRES_PASSWORD")

# ── PostgreSQL / PgBouncer connection config ─────────────────────────
# When using PgBouncer, set PGBOUNCER_MODE=true and point POSTGRES_HOST
# to the PgBouncer instance (default localhost:6432).
PGBOUNCER_MODE = os.getenv("PGBOUNCER_MODE", "false").lower() == "true"

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 6432 if PGBOUNCER_MODE else 5432)),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", db_pass),
    "database": os.getenv("POSTGRES_DATABASE", "battle_royale"),
}

# ── Connection Pool Tuning (for ~300 concurrent users) ──────────────
# With PgBouncer in transaction mode:
#   - App pool only needs ~20 connections (PgBouncer multiplexes)
#   - PgBouncer handles the 300+ client connections
# Without PgBouncer:
#   - Use up to 25 connections (PostgreSQL default max = 100)
#   - Each DB query is fast (<5ms), so 25 is plenty for 300 users
_POOL_MIN = int(os.getenv("DB_POOL_MIN", 5))
_POOL_MAX = int(os.getenv("DB_POOL_MAX", 20 if PGBOUNCER_MODE else 25))

# Connection pool
connection_pool = None


def get_connection_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        pool_kwargs = {
            "minconn": _POOL_MIN,
            "maxconn": _POOL_MAX,
            "host": DB_CONFIG["host"],
            "port": DB_CONFIG["port"],
            "user": DB_CONFIG["user"],
            "password": DB_CONFIG["password"],
            "database": DB_CONFIG["database"],
        }
        # PgBouncer in transaction mode: disable prepared statements
        if PGBOUNCER_MODE:
            pool_kwargs["options"] = "-c statement_timeout=30000"
        connection_pool = pool.ThreadedConnectionPool(**pool_kwargs)
    return connection_pool


def init_database():
    """Initialize the PostgreSQL database with required tables and indexes."""
    # First connect to default 'postgres' database to create our database
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database="postgres",
        )
        conn.autocommit = True
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_CONFIG["database"],))
        if not cursor.fetchone():
            cursor.execute(f'CREATE DATABASE "{DB_CONFIG["database"]}"')

        cursor.close()
        conn.close()
    except psycopg2.Error as e:
        print(f"Error creating database: {e}")
        raise

    # Now connect to our database and create tables
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Teams table (password_hash widened to 255 for bcrypt)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id VARCHAR(8) PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            members JSONB NOT NULL,
            endpoint_url TEXT NOT NULL,
            eliminated BOOLEAN DEFAULT FALSE,
            total_score DOUBLE PRECISION DEFAULT 0,
            seed INTEGER,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Matches table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id VARCHAR(36) PRIMARY KEY,
            round_number INTEGER NOT NULL,
            match_index INTEGER NOT NULL,
            team1_id VARCHAR(8) REFERENCES teams(id) ON DELETE SET NULL,
            team2_id VARCHAR(8) REFERENCES teams(id) ON DELETE SET NULL,
            team1_name VARCHAR(255),
            team2_name VARCHAR(255),
            team1_seed INTEGER,
            team2_seed INTEGER,
            team1_total DOUBLE PRECISION DEFAULT 0,
            team2_total DOUBLE PRECISION DEFAULT 0,
            winner_id VARCHAR(8) REFERENCES teams(id) ON DELETE SET NULL,
            winner_name VARCHAR(255),
            sub_round_prompts JSONB DEFAULT '{"1": null, "2": null, "3": null}',
            sub_rounds_completed JSONB DEFAULT '[]',
            completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Submissions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id VARCHAR(36) PRIMARY KEY,
            team_id VARCHAR(8) NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            team_name VARCHAR(255) NOT NULL,
            match_id VARCHAR(36) NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            sub_round INTEGER NOT NULL,
            sub_round_category VARCHAR(50) NOT NULL,
            prompt_sent TEXT,
            response_text TEXT,
            timestamp TIMESTAMP,
            score DOUBLE PRECISION,
            reasoning TEXT,
            fetch_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Indexes for query performance ────────────────────────────────
    index_queries = [
        # Teams: lookup by name (login, duplicate check)
        "CREATE INDEX IF NOT EXISTS idx_teams_name ON teams (name)",
        "CREATE INDEX IF NOT EXISTS idx_teams_eliminated ON teams (eliminated)",
        # Matches: lookup by round (bracket display, round management)
        "CREATE INDEX IF NOT EXISTS idx_matches_round ON matches (round_number, match_index)",
        "CREATE INDEX IF NOT EXISTS idx_matches_completed ON matches (completed)",
        # Submissions: lookup by match + sub_round (judging, scoring)
        "CREATE INDEX IF NOT EXISTS idx_submissions_match ON submissions (match_id, sub_round)",
        "CREATE INDEX IF NOT EXISTS idx_submissions_team_match ON submissions (team_id, match_id, sub_round)",
    ]
    for query in index_queries:
        try:
            cursor.execute(query)
        except Exception:
            pass

    # Migrations for existing tables
    migration_queries = [
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS team1_seed INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS team2_seed INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS winner_name VARCHAR(255)",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS sub_round_prompts JSONB DEFAULT '{\"1\": null, \"2\": null, \"3\": null}'",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS sub_rounds_completed JSONB DEFAULT '[]'",
        # Widen password_hash for bcrypt (SHA-256 was 64 chars, bcrypt needs ~60)
        "ALTER TABLE teams ALTER COLUMN password_hash TYPE VARCHAR(255)",
    ]
    for query in migration_queries:
        try:
            cursor.execute(query)
        except Exception:
            pass

    conn.commit()
    cursor.close()
    conn.close()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with automatic salting."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


@contextmanager
def get_db_connection():
    """Get a database connection from the pool with auto-rollback on error."""
    p = get_connection_pool()
    conn = p.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


# ── Helper: single row from query ────────────────────────────────────
def _fetch_one(query: str, params: tuple = ()) -> Optional[Dict]:
    """Execute a query and return a single row as dict, or None."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()
            return row


def _fetch_all(query: str, params: tuple = ()) -> List[Dict]:
    """Execute a query and return all rows as list of dicts."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.commit()
            return rows


def _execute(query: str, params: tuple = ()) -> int:
    """Execute a write query (INSERT/UPDATE/DELETE) and return rowcount."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
            return cur.rowcount


# ═════════════════════════════════════════════════════════════════════
# TEAM REPOSITORY
# ═════════════════════════════════════════════════════════════════════

def _row_to_team(row: Dict) -> Dict:
    """Convert a database row to a team dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "members": row["members"],
        "endpoint_url": row["endpoint_url"],
        "eliminated": bool(row["eliminated"]),
        "total_score": row["total_score"] or 0,
        "seed": row["seed"],
        "is_admin": bool(row["is_admin"]),
    }


class TeamRepository:
    """Repository for team-related database operations."""

    @staticmethod
    def create_team(name: str, password: str, members: List[Dict[str, str]], endpoint_url: str, is_admin: bool = False) -> Dict:
        """Create a new team — uses INSERT ... RETURNING to avoid re-query."""
        team_id = str(uuid.uuid4())[:8]
        password_hash = hash_password(password)
        members_json = json.dumps(members)

        row = _fetch_one("""
            INSERT INTO teams (id, name, password_hash, members, endpoint_url, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, members, endpoint_url, eliminated, total_score, seed, is_admin
        """, (team_id, name, password_hash, members_json, endpoint_url, is_admin))

        return _row_to_team(row) if row else {
            "id": team_id, "name": name, "members": members,
            "endpoint_url": endpoint_url, "eliminated": False,
            "total_score": 0, "seed": None, "is_admin": is_admin,
        }

    @staticmethod
    def get_team_by_name(name: str) -> Optional[Dict]:
        """Get a team by name (uses idx_teams_name index)."""
        row = _fetch_one("SELECT * FROM teams WHERE name = %s", (name,))
        return _row_to_team(row) if row else None

    @staticmethod
    def get_team_by_id(team_id: str) -> Optional[Dict]:
        """Get a team by ID (primary key lookup)."""
        row = _fetch_one("SELECT * FROM teams WHERE id = %s", (team_id,))
        return _row_to_team(row) if row else None

    @staticmethod
    def authenticate_team(name: str, password: str) -> Optional[Dict]:
        """Authenticate a team — single query, password verified in Python."""
        row = _fetch_one("SELECT * FROM teams WHERE name = %s", (name,))
        if row and verify_password(password, row["password_hash"]):
            return _row_to_team(row)
        return None

    @staticmethod
    def get_all_teams() -> List[Dict]:
        """Get all teams sorted by score."""
        rows = _fetch_all("SELECT * FROM teams ORDER BY total_score DESC")
        return [_row_to_team(r) for r in rows]

    @staticmethod
    def get_active_teams() -> List[Dict]:
        """Get non-eliminated teams (uses idx_teams_eliminated index)."""
        rows = _fetch_all(
            "SELECT * FROM teams WHERE eliminated = FALSE ORDER BY seed NULLS LAST, total_score DESC"
        )
        return [_row_to_team(r) for r in rows]

    @staticmethod
    def update_team_score(team_id: str, total_score: float):
        """Update a team's total score."""
        _execute("UPDATE teams SET total_score = %s WHERE id = %s", (total_score, team_id))

    @staticmethod
    def eliminate_team(team_id: str):
        """Mark a team as eliminated."""
        _execute("UPDATE teams SET eliminated = TRUE WHERE id = %s", (team_id,))

    @staticmethod
    def delete_team(team_id: str) -> bool:
        """Permanently delete a team. Returns True if deleted."""
        return _execute("DELETE FROM teams WHERE id = %s", (team_id,)) > 0

    @staticmethod
    def set_team_seed(team_id: str, seed: int):
        """Set a team's seed."""
        _execute("UPDATE teams SET seed = %s WHERE id = %s", (seed, team_id))

    @staticmethod
    def update_team_endpoint(team_id: str, endpoint_url: str) -> Optional[Dict]:
        """Update endpoint URL — uses RETURNING to avoid re-query."""
        row = _fetch_one(
            "UPDATE teams SET endpoint_url = %s WHERE id = %s "
            "RETURNING id, name, members, endpoint_url, eliminated, total_score, seed, is_admin",
            (endpoint_url, team_id)
        )
        return _row_to_team(row) if row else None

    @staticmethod
    def update_team_members(team_id: str, members: List[Dict[str, str]]) -> Optional[Dict]:
        """Update members — uses RETURNING to avoid re-query."""
        row = _fetch_one(
            "UPDATE teams SET members = %s WHERE id = %s "
            "RETURNING id, name, members, endpoint_url, eliminated, total_score, seed, is_admin",
            (json.dumps(members), team_id)
        )
        return _row_to_team(row) if row else None

    @staticmethod
    def set_team_admin(team_id: str, is_admin: bool):
        """Set a team's admin status."""
        _execute("UPDATE teams SET is_admin = %s WHERE id = %s", (is_admin, team_id))


# ═════════════════════════════════════════════════════════════════════
# MATCH REPOSITORY
# ═════════════════════════════════════════════════════════════════════

def _row_to_match(row: Dict) -> Dict:
    """Convert a database row to a match dict."""
    sub_round_prompts = row.get("sub_round_prompts") or {}
    if isinstance(sub_round_prompts, str):
        sub_round_prompts = json.loads(sub_round_prompts)
    sub_round_prompts = {int(k): v for k, v in sub_round_prompts.items()}

    sub_rounds_completed = row.get("sub_rounds_completed") or []
    if isinstance(sub_rounds_completed, str):
        sub_rounds_completed = json.loads(sub_rounds_completed)

    return {
        "id": row["id"],
        "round_number": row["round_number"],
        "match_index": row["match_index"],
        "team1_id": row["team1_id"],
        "team2_id": row["team2_id"],
        "team1_name": row["team1_name"],
        "team2_name": row["team2_name"],
        "team1_seed": row["team1_seed"],
        "team2_seed": row["team2_seed"],
        "team1_total": row["team1_total"] or 0,
        "team2_total": row["team2_total"] or 0,
        "winner_id": row["winner_id"],
        "winner_name": row["winner_name"],
        "sub_round_prompts": sub_round_prompts,
        "sub_rounds_completed": sub_rounds_completed,
        "completed": bool(row["completed"]),
    }


class MatchRepository:
    """Repository for match-related database operations."""

    @staticmethod
    def create_match(match: Dict) -> Dict:
        """Create a new match."""
        _execute("""
            INSERT INTO matches (id, round_number, match_index, team1_id, team2_id,
                team1_name, team2_name, team1_seed, team2_seed, team1_total, team2_total,
                winner_id, winner_name, sub_round_prompts, sub_rounds_completed, completed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            match["id"], match["round_number"], match["match_index"],
            match.get("team1_id"), match.get("team2_id"),
            match.get("team1_name"), match.get("team2_name"),
            match.get("team1_seed"), match.get("team2_seed"),
            match.get("team1_total", 0), match.get("team2_total", 0),
            match.get("winner_id"), match.get("winner_name"),
            json.dumps(match.get("sub_round_prompts", {1: None, 2: None, 3: None})),
            json.dumps(match.get("sub_rounds_completed", [])),
            match.get("completed", False)
        ))
        return match

    @staticmethod
    def get_match_by_id(match_id: str) -> Optional[Dict]:
        """Get a match by ID (primary key lookup)."""
        row = _fetch_one("SELECT * FROM matches WHERE id = %s", (match_id,))
        return _row_to_match(row) if row else None

    @staticmethod
    def get_all_matches() -> List[Dict]:
        """Get all matches ordered by round and index (uses idx_matches_round)."""
        rows = _fetch_all("SELECT * FROM matches ORDER BY round_number, match_index")
        return [_row_to_match(r) for r in rows]

    @staticmethod
    def get_matches_for_round(round_number: int) -> List[Dict]:
        """Get matches for a specific round (uses idx_matches_round index)."""
        rows = _fetch_all(
            "SELECT * FROM matches WHERE round_number = %s ORDER BY match_index",
            (round_number,)
        )
        return [_row_to_match(r) for r in rows]

    @staticmethod
    def update_match(match: Dict):
        """Update match scores, winner, and completion status."""
        _execute("""
            UPDATE matches SET
                team1_total = %s, team2_total = %s,
                winner_id = %s, winner_name = %s,
                sub_round_prompts = %s, sub_rounds_completed = %s,
                completed = %s
            WHERE id = %s
        """, (
            match.get("team1_total", 0), match.get("team2_total", 0),
            match.get("winner_id"), match.get("winner_name"),
            json.dumps(match.get("sub_round_prompts", {})),
            json.dumps(match.get("sub_rounds_completed", [])),
            match.get("completed", False),
            match["id"]
        ))

    @staticmethod
    def delete_matches_for_round(round_number: int):
        """Delete all matches for a round (cascades to submissions via FK)."""
        _execute("DELETE FROM matches WHERE round_number = %s", (round_number,))

    @staticmethod
    def delete_all_matches():
        """Delete all matches."""
        _execute("DELETE FROM matches")

    @staticmethod
    def _row_to_match(row: Dict) -> Dict:
        return _row_to_match(row)


# ═════════════════════════════════════════════════════════════════════
# SUBMISSION REPOSITORY
# ═════════════════════════════════════════════════════════════════════

def _row_to_submission(row: Dict) -> Dict:
    """Convert a database row to a submission dict."""
    return {
        "id": row["id"],
        "team_id": row["team_id"],
        "team_name": row["team_name"],
        "match_id": row["match_id"],
        "sub_round": row["sub_round"],
        "sub_round_category": row["sub_round_category"],
        "prompt_sent": row["prompt_sent"],
        "response_text": row["response_text"],
        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
        "score": row["score"],
        "reasoning": row["reasoning"],
        "fetch_error": row["fetch_error"],
    }


class SubmissionRepository:
    """Repository for submission-related database operations."""

    @staticmethod
    def create_submission(submission: Dict) -> Dict:
        """Create a new submission."""
        _execute("""
            INSERT INTO submissions (id, team_id, team_name, match_id, sub_round,
                sub_round_category, prompt_sent, response_text, timestamp, score,
                reasoning, fetch_error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            submission["id"], submission["team_id"], submission["team_name"],
            submission["match_id"], submission["sub_round"], submission["sub_round_category"],
            submission.get("prompt_sent"), submission.get("response_text"),
            submission.get("timestamp"), submission.get("score"),
            submission.get("reasoning"), submission.get("fetch_error")
        ))
        return submission

    @staticmethod
    def get_submission_by_id(submission_id: str) -> Optional[Dict]:
        """Get a submission by ID."""
        row = _fetch_one("SELECT * FROM submissions WHERE id = %s", (submission_id,))
        return _row_to_submission(row) if row else None

    @staticmethod
    def get_all_submissions() -> List[Dict]:
        """Get all submissions ordered by creation time."""
        rows = _fetch_all("SELECT * FROM submissions ORDER BY created_at")
        return [_row_to_submission(r) for r in rows]

    @staticmethod
    def get_submissions_for_match(match_id: str) -> List[Dict]:
        """Get submissions for a match (uses idx_submissions_match index)."""
        rows = _fetch_all(
            "SELECT * FROM submissions WHERE match_id = %s ORDER BY sub_round, team_name",
            (match_id,)
        )
        return [_row_to_submission(r) for r in rows]

    @staticmethod
    def get_submission_for_team_match_subround(team_id: str, match_id: str, sub_round: int) -> Optional[Dict]:
        """Get a specific submission (uses idx_submissions_team_match composite index)."""
        row = _fetch_one(
            "SELECT * FROM submissions WHERE team_id = %s AND match_id = %s AND sub_round = %s",
            (team_id, match_id, sub_round)
        )
        return _row_to_submission(row) if row else None

    @staticmethod
    def update_submission(submission: Dict):
        """Update submission response, score, and error fields."""
        _execute("""
            UPDATE submissions SET
                response_text = %s, timestamp = %s, score = %s,
                reasoning = %s, fetch_error = %s
            WHERE id = %s
        """, (
            submission.get("response_text"), submission.get("timestamp"),
            submission.get("score"), submission.get("reasoning"),
            submission.get("fetch_error"), submission["id"]
        ))

    @staticmethod
    def delete_submissions_for_match(match_id: str):
        """Delete submissions for a match (uses idx_submissions_match)."""
        _execute("DELETE FROM submissions WHERE match_id = %s", (match_id,))

    @staticmethod
    def delete_all_submissions():
        """Delete all submissions."""
        _execute("DELETE FROM submissions")


# ── Initialize on import ─────────────────────────────────────────────
try:
    init_database()
except Exception as e:
    print(f"WARNING: Database initialization failed: {e}")
    print("The application will continue but database features may not work.")
    print("Make sure PostgreSQL is running and credentials are correct.")
