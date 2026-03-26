import os
import random
import string
import time
from urllib.parse import urlparse

import gevent
import websocket
from locust import HttpUser, User, between, task


def _random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _api_base() -> str:
    return os.getenv("TARGET_HOST", "https://battle.kartikeya.me")


def _ws_url() -> str:
    default = "wss://battle.kartikeya.me/ws"
    explicit = os.getenv("WS_URL", default)
    if explicit.startswith("http://"):
        return explicit.replace("http://", "ws://", 1)
    if explicit.startswith("https://"):
        return explicit.replace("https://", "wss://", 1)
    return explicit


class ViewerTrafficUser(HttpUser):
    """Represents spectators/participants repeatedly polling public APIs."""

    wait_time = between(1, 4)

    @task(5)
    def get_state(self):
        self.client.get("/api/state", name="GET /api/state")

    @task(3)
    def get_standings(self):
        self.client.get("/api/standings", name="GET /api/standings")

    @task(2)
    def get_bracket(self):
        self.client.get("/api/bracket", name="GET /api/bracket")


class LoginBurstUser(HttpUser):
    """Represents users trying to login around the same time."""

    wait_time = between(15, 30)

    def on_start(self):
        base = os.getenv("LOCUST_TEAM_PREFIX", "loadtest-team")
        suffix = _random_suffix()
        self.team_name = f"{base}-{suffix}"
        self.password = os.getenv("LOCUST_TEAM_PASSWORD", "Loadtest#123")

        # Best effort registration for each virtual user.
        payload = {
            "name": self.team_name,
            "password": self.password,
            "members": [{"name": "Load Tester", "roll": suffix}],
            "endpoint_url": "https://example.com/generate",
        }
        self.client.post("/api/teams", json=payload, name="POST /api/teams (register)")

    @task
    def login(self):
        payload = {"name": self.team_name, "password": self.password}
        self.client.post("/api/teams/login", json=payload, name="POST /api/teams/login")


class WebSocketUser(User):
    """Keeps a WebSocket connection open to validate concurrent WS capacity."""

    wait_time = between(10, 20)
    abstract = False

    def on_start(self):
        self.ws = None
        self.running = True
        self._open_socket()
        self.recv_greenlet = gevent.spawn(self._recv_loop)

    def _open_socket(self):
        # Reuse Locust host override if provided.
        ws_url = _ws_url()
        host = self.environment.host
        if host:
            parsed = urlparse(host)
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = f"{ws_scheme}://{parsed.netloc}/ws"

        start = time.perf_counter()
        try:
            self.ws = websocket.create_connection(ws_url, timeout=10)
            duration_ms = (time.perf_counter() - start) * 1000
            self.environment.events.request.fire(
                request_type="WS",
                name="CONNECT /ws",
                response_time=duration_ms,
                response_length=0,
                exception=None,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            self.environment.events.request.fire(
                request_type="WS",
                name="CONNECT /ws",
                response_time=duration_ms,
                response_length=0,
                exception=exc,
            )
            self.ws = None

    def _recv_loop(self):
        while self.running:
            if not self.ws:
                gevent.sleep(2)
                self._open_socket()
                continue

            try:
                self.ws.settimeout(5)
                _ = self.ws.recv()
            except Exception:
                # Idle timeout or disconnect; reconnect on next iteration.
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None

    @task
    def keepalive(self):
        if not self.ws:
            gevent.sleep(1)
            return

        start = time.perf_counter()
        try:
            self.ws.send("ping")
            duration_ms = (time.perf_counter() - start) * 1000
            self.environment.events.request.fire(
                request_type="WS",
                name="SEND /ws",
                response_time=duration_ms,
                response_length=4,
                exception=None,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            self.environment.events.request.fire(
                request_type="WS",
                name="SEND /ws",
                response_time=duration_ms,
                response_length=0,
                exception=exc,
            )
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def on_stop(self):
        self.running = False
        if hasattr(self, "recv_greenlet") and self.recv_greenlet is not None:
            self.recv_greenlet.kill(block=False)
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
