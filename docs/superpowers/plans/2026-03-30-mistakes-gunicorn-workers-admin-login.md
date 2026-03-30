# Mistakes Article: Why Gunicorn Workers Broke Admin Logins In Production

## Incident Summary

In production, admin users could log in successfully, then immediately get `401 Invalid or expired token` on protected admin APIs.

This looked like a bad password or token expiry issue, but the real cause was deployment topology: multiple Gunicorn workers with process-local auth state.

## What Failed

Admin auth uses an in-memory token store:

- Login endpoint creates token in `_admin_tokens`.
- Protected endpoints call `verify_admin`, which checks `_admin_tokens`.

Both are implemented in these exact locations:

- Token store declaration: [backend/routes/admin.py](backend/routes/admin.py#L19)
- Login route declaration: [backend/routes/admin.py](backend/routes/admin.py#L97)
- Token write on login: [backend/routes/admin.py](backend/routes/admin.py#L104)
- Token verification dependency: [backend/routes/admin.py](backend/routes/admin.py#L86)
- Token lookup during verification: [backend/routes/admin.py](backend/routes/admin.py#L91)

With Gunicorn `--workers > 1`, each worker is a separate Python process with its own memory.

Result:

1. Login request lands on Worker A, token is stored in Worker A memory.
2. Next request lands on Worker B.
3. Worker B does not have that token.
4. `verify_admin` rejects it with 401.

So the token is valid from user perspective, but invalid from the process that received the request.

## Why This Happened

The backend architecture still has several in-memory, process-local components:

- Admin token map: `_admin_tokens`
- Tournament state singleton: `state`
- Timer task holder: `_timer_task`
- WebSocket manager connection list: `manager`

These work reliably only when all requests for the app are handled by one backend process.

Code references for process-local state:

- Timer task holder: [backend/routes/admin.py](backend/routes/admin.py#L18)
- Tournament app-state singleton: [backend/models.py](backend/models.py#L292)
- WebSocket manager singleton: [backend/ws_manager.py](backend/ws_manager.py#L47)

## Was Gunicorn Worker Usage Wrong?

Using Gunicorn workers is generally good practice for stateless APIs.

But this app is currently not fully stateless. In this architecture, multiple workers are not safe unless shared state is introduced.

So the mistake was not "using Gunicorn" itself.
The mistake was "scaling process count without externalizing process-local state".

## Current Safe Practice For This Repository

Use one backend worker in production until state/session redesign is complete.

The current backend container command already pins this correctly:

- Gunicorn command with one worker: [infra/docker/backend.Dockerfile](infra/docker/backend.Dockerfile#L22)

This avoids split-brain behavior for auth, timer events, bracket state, and websocket broadcasts.

## Where Production Went Wrong

Typical failure path observed in production setups:

1. Deployment was configured with multiple workers for higher throughput.
2. Auth/session logic remained in process memory.
3. Load balancing across workers made token verification non-deterministic.
4. Users saw random login failures despite correct credentials.

Secondary risks from the same pattern:

- Inconsistent bracket state across requests.
- Timer stop/start affecting one worker only.
- Partial websocket broadcasts to clients attached to different workers.

## Short-Term Fix (Recommended Now)

1. Keep Gunicorn at `--workers 1`.
2. Keep one backend replica for this stateful design.
3. Monitor restart frequency, because in-memory tokens are lost on process restart.

## Long-Term Correct Fix (Scale Safely)

To safely run multiple workers and replicas:

1. Move admin sessions/tokens to shared storage (Redis or DB), or use signed JWT with proper revocation strategy.
2. Move tournament state out of process memory (DB + transactional updates, or Redis with locking).
3. Add cross-worker pub/sub for websocket fanout (Redis pub/sub or message broker).
4. Keep request handlers idempotent and lock critical transitions.

After these changes, scaling Gunicorn workers becomes a good practice for this app too.

## Final Takeaway

Multi-worker Gunicorn is good for stateless services.
This application currently behaves as a stateful real-time coordinator.

Until shared state is implemented, one worker is the correct production setting.
