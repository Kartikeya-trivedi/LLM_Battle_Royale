import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Allow running `uvicorn main:app` from inside the backend directory.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load env vars before anything else
load_dotenv(BASE_DIR / ".env")

# Ensure logs directory exists
os.makedirs(BASE_DIR / "logs", exist_ok=True)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.teams import router as teams_router
from backend.routes.submissions import router as submissions_router
from backend.routes.admin import router as admin_router
from backend.ws_manager import manager
from backend.models import state
import backend.database as _database  # noqa: F401

app = FastAPI(title="InferenceX LLM Battle Royale", version="2.0.0")

# CORS — restrict to known origins (override via ALLOWED_ORIGINS env var)
_default_origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else _default_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(teams_router)
app.include_router(submissions_router)
app.include_router(admin_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "teams": len(state.get_all_teams()),
        "bracket_round": state.current_bracket_round,
        "sub_round": state.current_sub_round,
    }

@app.get("/api/state")
async def get_public_state():
    """Publicly accessible state dump — strips sensitive fields."""
    full = state.to_dict()
    # Strip sensitive fields from teams for public consumption
    safe_teams = []
    for t in full.get("teams", []):
        safe_team = {k: v for k, v in t.items() if k not in ("endpoint_url", "password_hash", "is_admin")}
        safe_teams.append(safe_team)
    full["teams"] = safe_teams
    return full


@app.get("/api/standings")
async def get_standings():
    """All teams with standings, sorted by total score. Strips sensitive fields."""
    teams = state.get_standings()
    safe_teams = []
    for t in teams:
        safe_team = {k: v for k, v in t.items() if k not in ("endpoint_url", "password_hash", "is_admin")}
        safe_teams.append(safe_team)
    return safe_teams


@app.get("/api/bracket")
async def get_bracket():
    """Get full bracket state."""
    return {
        "matches": list(state.matches.values()),
        "bracket_rounds": state.bracket_rounds,
        "current_bracket_round": state.current_bracket_round,
        "current_sub_round": state.current_sub_round,
        "total_bracket_rounds": state.total_bracket_rounds,
        "champion": state.champion,
    }


# WebSocket 

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
