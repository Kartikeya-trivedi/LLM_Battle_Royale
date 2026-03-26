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

# PostgreSQL connection configuration
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", db_pass),
    "database": os.getenv("POSTGRES_DATABASE", "battle_royale"),
}

# Connection pool for better performance
connection_pool = None


def get_connection_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        connection_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )
    return connection_pool


def init_database():
    """Initialize the PostgreSQL database with required tables."""
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

        # Create database if not exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = %s", (DB_CONFIG["database"],))
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

    # Teams table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id VARCHAR(8) PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(64) NOT NULL,
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

    # Add missing columns to existing tables (migrations)
    migration_queries = [
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS team1_seed INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS team2_seed INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS winner_name VARCHAR(255)",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS sub_round_prompts JSONB DEFAULT '{\"1\": null, \"2\": null, \"3\": null}'",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS sub_rounds_completed JSONB DEFAULT '[]'",
    ]
    for query in migration_queries:
        try:
            cursor.execute(query)
        except Exception:
            pass  # Column already exists

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
    """Get a database connection from the pool."""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


class TeamRepository:
    """Repository for team-related database operations."""

    @staticmethod
    def create_team(name: str, password: str, members: List[Dict[str, str]], endpoint_url: str, is_admin: bool = False) -> Dict:
        """Create a new team in the database."""
        team_id = str(uuid.uuid4())[:8]
        password_hash = hash_password(password)
        members_json = json.dumps(members)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO teams (id, name, password_hash, members, endpoint_url, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (team_id, name, password_hash, members_json, endpoint_url, is_admin))
            conn.commit()
            cursor.close()

            return {
                "id": team_id,
                "name": name,
                "members": members,
                "endpoint_url": endpoint_url,
                "eliminated": False,
                "total_score": 0,
                "seed": None,
                "is_admin": is_admin,
            }

    @staticmethod
    def get_team_by_name(name: str) -> Optional[Dict]:
        """Get a team by name."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM teams WHERE name = %s", (name,))
            result = cursor.fetchone()
            cursor.close()

            if result:
                return {
                    "id": result["id"],
                    "name": result["name"],
                    "members": result["members"],
                    "endpoint_url": result["endpoint_url"],
                    "eliminated": bool(result["eliminated"]),
                    "total_score": result["total_score"],
                    "seed": result["seed"],
                    "is_admin": bool(result["is_admin"]),
                }
            return None

    @staticmethod
    def get_team_by_id(team_id: str) -> Optional[Dict]:
        """Get a team by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
            result = cursor.fetchone()
            cursor.close()

            if result:
                return {
                    "id": result["id"],
                    "name": result["name"],
                    "members": result["members"],
                    "endpoint_url": result["endpoint_url"],
                    "eliminated": bool(result["eliminated"]),
                    "total_score": result["total_score"],
                    "seed": result["seed"],
                    "is_admin": bool(result["is_admin"]),
                }
            return None

    @staticmethod
    def authenticate_team(name: str, password: str) -> Optional[Dict]:
        """Authenticate a team with name and password."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM teams WHERE name = %s", (name,))
            result = cursor.fetchone()
            cursor.close()

            if result and verify_password(password, result["password_hash"]):
                return {
                    "id": result["id"],
                    "name": result["name"],
                    "members": result["members"],
                    "endpoint_url": result["endpoint_url"],
                    "eliminated": bool(result["eliminated"]),
                    "total_score": result["total_score"],
                    "seed": result["seed"],
                    "is_admin": bool(result["is_admin"]),
                }
            return None

    @staticmethod
    def get_all_teams() -> List[Dict]:
        """Get all teams."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM teams ORDER BY total_score DESC")
            rows = cursor.fetchall()
            cursor.close()

            return [{
                "id": row["id"],
                "name": row["name"],
                "members": row["members"],
                "endpoint_url": row["endpoint_url"],
                "eliminated": bool(row["eliminated"]),
                "total_score": row["total_score"],
                "seed": row["seed"],
                "is_admin": bool(row["is_admin"]),
            } for row in rows]

    @staticmethod
    def get_active_teams() -> List[Dict]:
        """Get all non-eliminated teams."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM teams WHERE eliminated = FALSE ORDER BY total_score DESC")
            rows = cursor.fetchall()
            cursor.close()

            return [{
                "id": row["id"],
                "name": row["name"],
                "members": row["members"],
                "endpoint_url": row["endpoint_url"],
                "eliminated": bool(row["eliminated"]),
                "total_score": row["total_score"],
                "seed": row["seed"],
                "is_admin": bool(row["is_admin"]),
            } for row in rows]

    @staticmethod
    def update_team_score(team_id: str, total_score: float):
        """Update a team's total score."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET total_score = %s WHERE id = %s", (total_score, team_id))
            conn.commit()
            cursor.close()

    @staticmethod
    def eliminate_team(team_id: str):
        """Mark a team as eliminated."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET eliminated = TRUE WHERE id = %s", (team_id,))
            conn.commit()
            cursor.close()

    @staticmethod
    def set_team_seed(team_id: str, seed: int):
        """Set a team's seed."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET seed = %s WHERE id = %s", (seed, team_id))
            conn.commit()
            cursor.close()

    @staticmethod
    def update_team_endpoint(team_id: str, endpoint_url: str) -> Optional[Dict]:
        """Update a team's endpoint URL."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET endpoint_url = %s WHERE id = %s", (endpoint_url, team_id))
            conn.commit()
            cursor.close()
        return TeamRepository.get_team_by_id(team_id)

    @staticmethod
    def update_team_members(team_id: str, members: List[Dict[str, str]]) -> Optional[Dict]:
        """Update a team's members."""
        members_json = json.dumps(members)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET members = %s WHERE id = %s", (members_json, team_id))
            conn.commit()
            cursor.close()
        return TeamRepository.get_team_by_id(team_id)

    @staticmethod
    def set_team_admin(team_id: str, is_admin: bool):
        """Set a team's admin status."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE teams SET is_admin = %s WHERE id = %s", (is_admin, team_id))
            conn.commit()
            cursor.close()


class MatchRepository:
    """Repository for match-related database operations."""

    @staticmethod
    def create_match(match: Dict) -> Dict:
        """Create a new match in the database."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
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
            conn.commit()
            cursor.close()
        return match

    @staticmethod
    def get_match_by_id(match_id: str) -> Optional[Dict]:
        """Get a match by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM matches WHERE id = %s", (match_id,))
            row = cursor.fetchone()
            cursor.close()
            if row:
                return MatchRepository._row_to_match(row)
            return None

    @staticmethod
    def get_all_matches() -> List[Dict]:
        """Get all matches."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM matches ORDER BY round_number, match_index")
            rows = cursor.fetchall()
            cursor.close()
            return [MatchRepository._row_to_match(row) for row in rows]

    @staticmethod
    def get_matches_for_round(round_number: int) -> List[Dict]:
        """Get all matches for a specific round."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT * FROM matches WHERE round_number = %s ORDER BY match_index",
                (round_number,)
            )
            rows = cursor.fetchall()
            cursor.close()
            return [MatchRepository._row_to_match(row) for row in rows]

    @staticmethod
    def update_match(match: Dict):
        """Update a match in the database."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
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
            conn.commit()
            cursor.close()

    @staticmethod
    def delete_matches_for_round(round_number: int):
        """Delete all matches for a specific round."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches WHERE round_number = %s", (round_number,))
            conn.commit()
            cursor.close()

    @staticmethod
    def delete_all_matches():
        """Delete all matches."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches")
            conn.commit()
            cursor.close()

    @staticmethod
    def _row_to_match(row: Dict) -> Dict:
        """Convert a database row to a match dict."""
        sub_round_prompts = row.get("sub_round_prompts") or {}
        if isinstance(sub_round_prompts, str):
            sub_round_prompts = json.loads(sub_round_prompts)
        # Convert string keys to int keys
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


class SubmissionRepository:
    """Repository for submission-related database operations."""

    @staticmethod
    def create_submission(submission: Dict) -> Dict:
        """Create a new submission in the database."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
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
            conn.commit()
            cursor.close()
        return submission

    @staticmethod
    def get_submission_by_id(submission_id: str) -> Optional[Dict]:
        """Get a submission by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM submissions WHERE id = %s", (submission_id,))
            row = cursor.fetchone()
            cursor.close()
            if row:
                return SubmissionRepository._row_to_submission(row)
            return None

    @staticmethod
    def get_all_submissions() -> List[Dict]:
        """Get all submissions."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM submissions ORDER BY created_at")
            rows = cursor.fetchall()
            cursor.close()
            return [SubmissionRepository._row_to_submission(row) for row in rows]

    @staticmethod
    def get_submissions_for_match(match_id: str) -> List[Dict]:
        """Get all submissions for a specific match."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT * FROM submissions WHERE match_id = %s ORDER BY sub_round, team_name",
                (match_id,)
            )
            rows = cursor.fetchall()
            cursor.close()
            return [SubmissionRepository._row_to_submission(row) for row in rows]

    @staticmethod
    def get_submission_for_team_match_subround(team_id: str, match_id: str, sub_round: int) -> Optional[Dict]:
        """Get a submission for a specific team, match, and sub-round."""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT * FROM submissions WHERE team_id = %s AND match_id = %s AND sub_round = %s",
                (team_id, match_id, sub_round)
            )
            row = cursor.fetchone()
            cursor.close()
            if row:
                return SubmissionRepository._row_to_submission(row)
            return None

    @staticmethod
    def update_submission(submission: Dict):
        """Update a submission in the database."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE submissions SET
                    response_text = %s, timestamp = %s, score = %s,
                    reasoning = %s, fetch_error = %s
                WHERE id = %s
            """, (
                submission.get("response_text"), submission.get("timestamp"),
                submission.get("score"), submission.get("reasoning"),
                submission.get("fetch_error"), submission["id"]
            ))
            conn.commit()
            cursor.close()

    @staticmethod
    def delete_submissions_for_match(match_id: str):
        """Delete all submissions for a specific match."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM submissions WHERE match_id = %s", (match_id,))
            conn.commit()
            cursor.close()

    @staticmethod
    def delete_all_submissions():
        """Delete all submissions."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM submissions")
            conn.commit()
            cursor.close()

    @staticmethod
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


# Initialize database when module is imported
try:
    init_database()
except Exception as e:
    print(f"WARNING: Database initialization failed: {e}")
    print("The application will continue but database features may not work.")
    print("Make sure PostgreSQL is running and credentials are correct.")
