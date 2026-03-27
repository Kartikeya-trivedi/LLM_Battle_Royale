from fastapi import APIRouter, HTTPException, Request
import httpx
import os
import re
from backend.models import state, TeamCreate, TeamOut, TeamLogin, TeamEndpointUpdate
from backend.ws_manager import manager
from backend.database import TeamRepository

router = APIRouter(prefix="/api/teams", tags=["teams"])

# ── Allowed endpoint domains (set via env or default to .modal.run) ──
_ALLOWED_ENDPOINT_DOMAINS = os.getenv("ALLOWED_ENDPOINT_DOMAINS", ".modal.run").split(",")


def _validate_endpoint_url(url: str) -> str:
    """Validate and return the cleaned endpoint URL."""
    url = url.strip()
    if url == "DUMMY":
        return url
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Endpoint URL must start with http:// or https://")
    # Domain whitelist check
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not any(hostname.endswith(domain.strip()) for domain in _ALLOWED_ENDPOINT_DOMAINS):
        allowed = ", ".join(d.strip() for d in _ALLOWED_ENDPOINT_DOMAINS)
        raise HTTPException(
            status_code=400,
            detail=f"Endpoint URL must be hosted on an allowed domain: {allowed}. Got: {hostname}"
        )
    return url


def _sanitize_team_name(name: str) -> str:
    """Sanitize team name: allow alphanumeric, spaces, hyphens, underscores, and common emoji."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Team name cannot be empty")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="Team name must be 50 characters or less")
    # Remove any HTML tags
    name = re.sub(r'<[^>]+>', '', name)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Team name contains only invalid characters")
    return name.strip()





@router.post("", response_model=TeamOut)
async def register_team(team: TeamCreate, request: Request):
    # Check if registration is open
    if not state.registration_open:
        raise HTTPException(status_code=403, detail="Registration is currently closed")


    # Sanitize team name
    clean_name = _sanitize_team_name(team.name)

    # Check for duplicate name
    if state.get_team_by_name(clean_name):
        raise HTTPException(status_code=400, detail="Team name already taken")

    if len(team.members) < 1 or len(team.members) > 4:
        raise HTTPException(status_code=400, detail="Teams must have 1-4 members")

    if len(team.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long")

    # Validate endpoint URL (domain whitelist)
    url = _validate_endpoint_url(team.endpoint_url)

    # Convert members to list of dicts for storage
    members_data = [{"name": m.name, "roll": m.roll} for m in team.members]
    new_team = state.add_team(clean_name, team.password, members_data, url)
    await manager.broadcast("team_registered", new_team)
    return new_team


@router.get("")
async def list_teams():
    """List all teams — hides endpoint URLs for security."""
    teams = state.get_all_teams()
    # Strip sensitive fields from public listing
    return [
        {k: v for k, v in t.items() if k not in ("endpoint_url", "password_hash", "is_admin")}
        for t in teams
    ]


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: str):
    team = state.get_team_by_id(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("/login")
async def login_team(login_data: TeamLogin):
    """Authenticate team with name and password — returns team data."""
    team = state.authenticate_team(login_data.name, login_data.password)
    if not team:
        raise HTTPException(status_code=401, detail="Invalid team name or password")
    return team


@router.put("/{team_id}/endpoint", response_model=TeamOut)
async def update_team_endpoint(team_id: str, data: TeamEndpointUpdate):
    """Update a team's endpoint URL."""
    team = state.get_team_by_id(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if endpoint editing is open
    if not state.endpoint_editing_open:
        raise HTTPException(status_code=403, detail="Endpoint editing is currently locked")

    url = data.endpoint_url.strip()
    url = _validate_endpoint_url(url)

    updated_team = TeamRepository.update_team_endpoint(team_id, url)
    await manager.broadcast("team_updated", updated_team)
    return updated_team


@router.post("/test-endpoint")
async def test_endpoint(data: dict):
    """Test a team's LLM endpoint URL — no auth required."""
    url = data.get("url", "").strip()
    if not url:
        return {"success": False, "error": "URL is required"}

    prompt = data.get("prompt", "What is 2+2? Answer in one line.")

    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"prompt": prompt},
                headers={"Content-Type": "application/json"},
            )
            latency_ms = round((time.time() - start) * 1000, 1)

            if response.status_code >= 400:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

            resp_data = response.json()
            if isinstance(resp_data, str):
                response_text = resp_data
            elif isinstance(resp_data, dict):
                response_text = (
                    resp_data.get("response")
                    or resp_data.get("text")
                    or resp_data.get("output")
                    or resp_data.get("generated_text")
                    or str(resp_data)
                )
            else:
                response_text = str(resp_data)

            return {
                "success": True,
                "response": response_text,
                "latency_ms": latency_ms,
                "status_code": response.status_code,
            }

    except httpx.TimeoutException:
        return {"success": False, "error": "Endpoint timed out after 10 seconds"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {str(e)[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}

